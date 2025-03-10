################################################################################
# app.py
################################################################################

import streamlit as st
# (1) Set page config debe ser lo primero que hagamos con Streamlit
st.set_page_config(
    layout="wide",
    page_title="Dashboard de horas y ausencias",
    initial_sidebar_state="collapsed"
)

import os
import requests
import pandas as pd
import holidays
import plotly.graph_objects as go
from datetime import datetime, date
from workalendar.europe.spain import Catalonia
from calendar import monthrange
from dotenv import load_dotenv

# (2) Importamos la configuración desde config.py y cargamos sus valores
from config import Config
config = Config.load_config()


################################################################################
# 1. CONFIGURACIONES Y CONSTANTES
################################################################################

# Usamos los valores cargados desde config
FACTORIAL_API_KEY = config['FACTORIAL_API_KEY']
FACTORIAL_BASE_URL = config['FACTORIAL_BASE_URL']
API_KEY_COR = config['COR_API_KEY']
CLIENT_SECRET_COR = config['COR_CLIENT_SECRET']
BASE_URL_COR = config['COR_BASE_URL']

HEADERS_FACTORIAL = {
    "accept": "application/json",
    "x-api-key": FACTORIAL_API_KEY,
}

# Festivos: España - Barcelona
festivos_barcelona = holidays.Spain(subdiv="CT")

# Nombres de meses en español
NOMBRES_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]

# Empleados no productivos (ejemplo)
EMPLEADOS_NO_PRODUCTIVOS = {
    "celia henriquez",
    "andrea martínez"
}

# Mapeo de nombres para normalizar
NOMBRE_MAPPING = {
    "albert sunyer": "albert sunyer vilafranca",
    "david collado": "david collado preciado",
    "esther janer": "esther janer roig",
    "vanessa dueñas": "vanessa dueñas moga",
    "ariadna de angulo": "ariadna de angulo villa",
    "norma vila": "norma vila muñoz",
    "mar esteva": "mar esteva fabrega",
    "mar esteva fàbrega": "mar esteva fabrega"
}

################################################################################
# 2. FUNCIONES AUXILIARES
################################################################################
def normalizar_nombre(nombre):
    """Normaliza el nombre del empleado para unificar diferentes versiones."""
    nombre_norm = ' '.join(nombre.lower().strip().split())
    return NOMBRE_MAPPING.get(nombre_norm, nombre_norm)

def obtener_token_cor(api_key, client_secret):
    """Obtiene el token de acceso usando client_credentials en COR."""
    url_token = f"{BASE_URL_COR}/v1/oauth/token?grant_type=client_credentials"
    import base64
    basic_creds = base64.b64encode(f"{api_key}:{client_secret}".encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": "Basic " + basic_creds,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    resp = requests.post(url_token, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        return data.get("access_token")
    else:
        st.error(f"Error al obtener el token: {resp.status_code} {resp.text}")
        return None

def obtener_tareas_cor(access_token, page=1, per_page=10):
    """Obtiene las tareas de COR, paginadas. Retorna el JSON con la respuesta."""
    url_tasks = f"{BASE_URL_COR}/v1/tasks?page={page}&perPage={per_page}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    resp = requests.get(url_tasks, headers=headers)

    if resp.status_code == 200:
        return resp.json()
    else:
        print("Error al obtener tareas:", resp.status_code, resp.text)
        return None

def calcular_dias_laborables_por_mes(inicio, fin):
    """Días laborables por mes (excluyendo sábados, domingos y festivos)."""
    try:
        dias = pd.date_range(start=inicio, end=fin, freq='B')  # L-V
        dias_laborables = dias[~dias.isin(festivos_barcelona)]  # Excluir festivos
        return dias_laborables.to_series().groupby(dias_laborables.to_period("M")).size()
    except ValueError:
        # Handle future dates by returning an empty Series
        return pd.Series(dtype=int)

def obtener_ausencias():
    """Obtiene todas las ausencias desde Factorial"""
    url = f"{FACTORIAL_BASE_URL}/resources/timeoff/leaves"
    params = {
        'per_page': 100,
        'page': 1,
        'include_future': True
    }
    
    todas_ausencias = []
    while True:
        response = requests.get(url, headers=HEADERS_FACTORIAL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        ausencias_pagina = data.get('data', [])
        if not ausencias_pagina:
            break
        todas_ausencias.extend(ausencias_pagina)
        if data.get('meta', {}).get('next_page'):
            params['page'] += 1
        else:
            break
    
    return todas_ausencias

def calcular_ausencias_empleado(empleado_nombre, anio, mes):
    """Calcula los días de ausencia (vacaciones, otras ausencias, teletrabajo)."""
    all_ausencias = obtener_ausencias()
    dias_vacaciones = 0
    dias_otras_ausencias = 0
    dias_teletrabajo = 0

    # IDs de ausencia que NO descuentan horas (solo teletrabajo)
    ids_no_descuentan = {2280065}  # Día extra teletrabajo
    ID_VACACIONES = 2276680

    empleado_nombre_norm = normalizar_nombre(empleado_nombre)
    mes_objetivo = pd.Period(f"{anio}-{mes:02d}")

    for ausencia in all_ausencias:
        nombre_ausencia = normalizar_nombre(ausencia.get("employee_full_name", ""))
        if nombre_ausencia != empleado_nombre_norm:
            continue

        inicio = pd.to_datetime(ausencia["start_on"])
        fin = pd.to_datetime(ausencia["finish_on"])
        mes_inicio = pd.Period(inicio, freq='M')
        mes_fin = pd.Period(fin, freq='M')

        # Skip if the absence doesn't overlap with target month
        if mes_objetivo < mes_inicio or mes_objetivo > mes_fin:
            continue

        # Get days for this specific month
        dias_periodo = calcular_dias_laborables_por_mes(inicio, fin)
        dias = dias_periodo.get(mes_objetivo, 0)

        tipo_id = ausencia.get("leave_type_id")
        if tipo_id in ids_no_descuentan:
            dias_teletrabajo += dias
        elif tipo_id == ID_VACACIONES:
            dias_vacaciones += dias
        else:  # All other absence types count as otras_ausencias
            dias_otras_ausencias += dias

    return dias_vacaciones, dias_otras_ausencias, dias_teletrabajo

def calcular_dias_laborables_festivos(year, month):
    """Devuelve (dias_laborables, festivos_laborables) para un año/mes en Cataluña."""
    cal = Catalonia()
    _, total_days = monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    dias_laborables = 0
    for day in range(1, total_days + 1):
        current_date = date(year, month, day)
        if current_date.weekday() < 5:  # L-V
            dias_laborables += 1

    festivos_laborables = 0
    holidays_year = cal.holidays(year)
    for dia, _ in holidays_year:
        if start_date <= dia <= end_date and dia.weekday() < 5:
            festivos_laborables += 1

    return (dias_laborables - festivos_laborables), festivos_laborables

def calcular_horas_disponibles(year, month, dias_vacaciones, dias_otras_ausencias=0, buffer_porcentaje=0.1):
    """
    Calcula horas disponibles tras restar vacaciones, ausencias y buffer.
    En agosto: 7h/día, resto: 8h/día.
    El buffer se ajusta proporcionalmente según los días de ausencia.
    """
    dias_laborables, _ = calcular_dias_laborables_festivos(year, month)
    horas_por_dia = 7 if month == 8 else 8
    dias_ausencia_total = dias_vacaciones + dias_otras_ausencias

    horas_brutas = dias_laborables * horas_por_dia
    horas_ausencias = dias_ausencia_total * horas_por_dia

    # Calculamos el porcentaje de ausencia del mes
    porcentaje_ausencia = dias_ausencia_total / dias_laborables if dias_laborables > 0 else 1
    # El buffer se reduce proporcionalmente según el porcentaje de ausencia
    buffer = (horas_brutas - horas_ausencias) * buffer_porcentaje * (1 - porcentaje_ausencia)
    
    return max(0, horas_brutas - horas_ausencias - buffer)

@st.cache_data(show_spinner=True)
def descargar_datos():
    """Descarga tareas de COR y ausencias de Factorial, genera dict empleadosPorMes."""
    st.cache_data.clear()  # Clear cache at the start
    access_token = obtener_token_cor(API_KEY_COR, CLIENT_SECRET_COR)
    if not access_token:
        st.error("No se pudo obtener el token de COR. Revisa credenciales.")
        return {}

    all_tasks = []
    page = 1
    per_page = 200

    while True:
        data = obtener_tareas_cor(access_token, page=page, per_page=per_page)
        if not data or "data" not in data:
            break

        tasks = data["data"]
        if not tasks:
            break

        # Filtramos tareas con horas cargadas o estimadas
        filtered = [t for t in tasks if (t.get("hour_charged", 0) > 0 or t.get("estimated", 0) > 0)]
        all_tasks.extend(filtered)
        page += 1

    empleadosPorMes = {}
    for task in all_tasks:
        dt_str = task.get("datetime")
        if not dt_str:
            continue

        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        year = dt_obj.year
        month = dt_obj.month
        nombre_mes = NOMBRES_MESES[month - 1]
        sheet_name = f"{nombre_mes}-{year}"

        if sheet_name not in empleadosPorMes:
            empleadosPorMes[sheet_name] = {}

        hour_charged = task.get("hour_charged", 0)
        estimated_min = task.get("estimated", 0)
        estimated_hours = estimated_min / 60.0

        colaboradores = task.get("collaborators", [])
        if not colaboradores:
            continue

        num_cols = len(colaboradores)
        if num_cols == 0:
            continue

        hc_por_colab = hour_charged / num_cols
        est_por_colab = estimated_hours / num_cols

        for colab in colaboradores:
            raw_name = f"{colab.get('first_name','')} {colab.get('last_name','')}".strip()
            colab_name = normalizar_nombre(raw_name)

            if colab_name not in empleadosPorMes[sheet_name]:
                empleadosPorMes[sheet_name][colab_name] = {
                    "horas_cargadas": 0.0,
                    "horas_estimadas": 0.0,
                    "vacaciones": 0,
                    "otras_ausencias": 0,
                    "teletrabajo": 0
                }

            empleadosPorMes[sheet_name][colab_name]["horas_cargadas"] += hc_por_colab
            empleadosPorMes[sheet_name][colab_name]["horas_estimadas"] += est_por_colab

    # Añadir ausencias
    for sheet_name, colaboradores in empleadosPorMes.items():
        try:
            mes_nombre, anio_str = sheet_name.split("-")
            anio = int(anio_str)
            mes = NOMBRES_MESES.index(mes_nombre) + 1

            for colaborador in colaboradores:
                try:
                    vac, otras, tele = calcular_ausencias_empleado(colaborador, anio, mes)
                    empleadosPorMes[sheet_name][colaborador]["vacaciones"] = vac
                    empleadosPorMes[sheet_name][colaborador]["otras_ausencias"] = otras
                    empleadosPorMes[sheet_name][colaborador]["teletrabajo"] = tele
                except ValueError as e:
                    print(f"Error procesando ausencias para {colaborador} en {sheet_name}: {e}")
                    empleadosPorMes[sheet_name][colaborador]["vacaciones"] = 0
                    empleadosPorMes[sheet_name][colaborador]["otras_ausencias"] = 0
                    empleadosPorMes[sheet_name][colaborador]["teletrabajo"] = 0

        except Exception as e:
            print(f"Error procesando {sheet_name}: {e}")

    return empleadosPorMes

################################################################################
# 3. FUNCIÓN PRINCIPAL (DASHBOARD)
################################################################################
def main():
    # CSS responsivo para modo claro/oscuro
    st.markdown("""
    <style>
    /* Adaptar colores al modo del navegador */
    @media (prefers-color-scheme: dark) {
      .stApp {
        background-color: #0E1117 !important;  /* Fondo oscuro */
        color: #DCDCDC !important;            /* Texto claro */
      }
      .css-1lcbmhc, .css-z5fcl4, .stMarkdown, .stDataFrame {
        color: #DCDCDC !important; /* Asegura que el texto en tablas y Markdown sea claro */
      }
      div[data-testid="stMetricValue"] {
        color: #F2F2F2 !important; /* Métricas - texto claro */
      }
      div[data-testid="stMetricLabel"] {
        color: #DDDDDD !important; /* Métricas - etiqueta clara */
      }
      .css-1n76uvr {
        background-color: #1A1D21 !important; /* Fondo de la tabla en modo oscuro */
      }
      /* Ajustes de color para títulos */
      h1, h2, h3, h4 {
        color: #ffffff !important;
      }
    }
    @media (prefers-color-scheme: light) {
      .stApp {
        background-color: #FFFFFF !important; /* Fondo claro */
        color: #000000 !important;           /* Texto oscuro */
      }
      div[data-testid="stMetricValue"], div[data-testid="stMetricLabel"] {
        color: #000000 !important; 
      }
      .css-1n76uvr {
        background-color: #F9F9F9 !important; /* Fondo de la tabla en modo claro */
      }
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("Dashboard de horas y ausencias (Factorial + COR)")

    # Botón para refrescar datos
    if st.button("🔄 Actualizar Datos"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    with st.spinner("Descargando datos de COR y Factorial..."):
        empleados_data = descargar_datos()

    if not empleados_data:
        st.warning("No se encontró información de tareas o el proceso falló.")
        return

    # Ordenar la lista de mes-año
    todos_los_meses = sorted(
        empleados_data.keys(),
        key=lambda x: (int(x.split("-")[1]), NOMBRES_MESES.index(x.split("-")[0]))
    )

    # Mes actual
    current_month = NOMBRES_MESES[datetime.now().month - 1]
    current_year = datetime.now().year
    current_month_year = f"{current_month}-{current_year}"

    try:
        current_index = todos_los_meses.index(current_month_year)
        start_index = max(0, current_index - 3)
        end_index = min(len(todos_los_meses), current_index + 2)
        meses_mostrados = todos_los_meses[start_index:end_index]
        default_index = meses_mostrados.index(current_month_year) if current_month_year in meses_mostrados else 0
    except ValueError:
        meses_mostrados = todos_los_meses[-5:] if len(todos_los_meses) > 5 else todos_los_meses
        default_index = len(meses_mostrados) - 1

    st.markdown("""
        <style>
        /* Ajuste visual del selectbox */
        div[data-testid="stSelectbox"] {
            max-width: 200px;
            margin: 0;
        }
        div[data-testid="stSelectbox"] > div > div {
            max-width: 200px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.write("Selecciona un mes/año para analizar:")
    mes_seleccionado = st.selectbox(
        label="Selección de mes y año",  # Added proper label
        options=meses_mostrados,
        index=default_index,
        label_visibility="collapsed"  # Keep it hidden
    )

    colaboradores_mes = empleados_data.get(mes_seleccionado, {})
    if not colaboradores_mes:
        st.info(f"No hay colaboradores con horas en {mes_seleccionado}")
        return

    # Cálculos globales del mes
    mes_nombre, anio_str = mes_seleccionado.split("-")
    anio = int(anio_str)
    mes_num = NOMBRES_MESES.index(mes_nombre) + 1

    dias_laborables, festivos_laborables = calcular_dias_laborables_festivos(anio, mes_num)
    horas_por_dia = 7 if mes_num == 8 else 8
    horas_mes_brutas = dias_laborables * horas_por_dia

    # Métricas
    col1, col2, col3 = st.columns(3)

    metrics_style = """
    <style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 1.5rem;
        text-align: center;
        height: 100%;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .metric-title {
        font-size: 1.1em;
        margin-bottom: 0.5em;
        color: #666;
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
        margin: 0;
        color: #2c3e50;
    }
    </style>
    """
    st.markdown(metrics_style, unsafe_allow_html=True)

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">📅 Días laborables</div>
            <div class="metric-value">{dias_laborables}</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">🎉 Festivos laborables</div>
            <div class="metric-value">{festivos_laborables}</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">⏰ Horas por día</div>
            <div class="metric-value">{horas_por_dia}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
        <div style='padding: 1em; border-radius: 10px; margin-bottom: 1em;'>
            <h2 style='margin: 0; padding: 0;'>📊 Resumen del mes</h2>
        </div>
    """, unsafe_allow_html=True)

    # Totales
    total_horas_disponibles = 0
    total_horas_estimadas = 0
    total_horas_cargadas = 0

    for colab, info in colaboradores_mes.items():
        if normalizar_nombre(colab) not in EMPLEADOS_NO_PRODUCTIVOS:
            v = info.get("vacaciones", 0)
            oa = info.get("otras_ausencias", 0)
            hd = calcular_horas_disponibles(anio, mes_num, v, oa, buffer_porcentaje=0.1)
            total_horas_disponibles += hd
            total_horas_estimadas += info.get("horas_estimadas", 0)
            total_horas_cargadas += info.get("horas_cargadas", 0)

    col1, col2, col3 = st.columns(3)

    metric_style = """
    <style>
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 1.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    div[data-testid="metric-container"] label {
        font-size: 1.2em !important;
        color: #666 !important;
    }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        font-size: 2.5em !important;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        transition: transform 0.2s ease;
    }
    </style>
    """
    st.markdown(metric_style, unsafe_allow_html=True)

    with col1:
        st.metric(
            label="Total Horas Disponibles",
            value=f"{total_horas_disponibles:.1f}h",
            delta=f"{(total_horas_disponibles - total_horas_estimadas):.1f}h sin planificar",
            delta_color="normal"
        )

    with col2:
        if total_horas_disponibles > 0:
            est_pct = (total_horas_estimadas / total_horas_disponibles) * 100
        else:
            est_pct = 0
        st.metric(
            label="Total Horas Estimadas",
            value=f"{total_horas_estimadas:.1f}h",
            delta=f"{est_pct:.1f}% de ocupación",
            delta_color="off"
        )

    with col3:
        if total_horas_disponibles > 0:
            ocupacion_real = (total_horas_cargadas / total_horas_disponibles) * 100
        else:
            ocupacion_real = 0
        st.metric(
            label="Total Horas Cargadas",
            value=f"{total_horas_cargadas:.1f}h",
            delta=f"{ocupacion_real:.1f}% ocupación real",
            delta_color="inverse"
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Detalle por colaborador
    data_rows = []
    for colaborador, info in colaboradores_mes.items():
        if normalizar_nombre(colaborador) in EMPLEADOS_NO_PRODUCTIVOS:
            continue
        v = info.get("vacaciones", 0)
        oa = info.get("otras_ausencias", 0)

        horas_disp = calcular_horas_disponibles(anio, mes_num, v, oa, buffer_porcentaje=0.1)
        hc = info.get("horas_cargadas", 0)
        he = info.get("horas_estimadas", 0)

        pct_est = (he / horas_disp * 100) if horas_disp > 0 else 0
        horas_disponibles_reales = horas_disp - he

        data_rows.append({
            "Colaborador": colaborador,
            "Carga %": min(pct_est, 100),
            "Vacaciones (días)": v,
            "Otras ausencias (días)": oa,
            "Horas Disponibles (c/Buffer)": round(horas_disp, 1),
            "Horas Estimadas (COR)": round(he, 1),
            "Horas Disponibles Reales": round(horas_disponibles_reales, 1),
            "Horas Cargadas (COR)": round(hc, 1)
        })
    df = pd.DataFrame(data_rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(len(df) * 35 + 40, 800),
        column_config={
            "Carga %": st.column_config.ProgressColumn(
                "Carga %",
                help="Porcentaje de horas estimadas respecto a las disponibles",
                format="%d%%",
                min_value=0,
                max_value=100,
            ),
            "Horas Disponibles (c/Buffer)": st.column_config.NumberColumn(
                "Horas Disponibles (c/Buffer) ℹ️",
                help="Horas disponibles del mes después de restar vacaciones, ausencias y un 10% de buffer para imprevistos"
            ),
            "Horas Estimadas (COR)": st.column_config.NumberColumn(
                "Horas Estimadas (COR) ℹ️",
                help="Horas planificadas en las tareas asignadas en COR"
            ),
            "Horas Disponibles Reales": st.column_config.NumberColumn(
                "Horas Disponibles Reales ℹ️",
                help="Horas realmente disponibles: Horas disponibles con buffer menos las horas estimadas"
            ),
            "Horas Cargadas (COR)": st.column_config.NumberColumn(
                "Horas Cargadas (COR) ℹ️",
                help="Horas ya registradas/imputadas en las tareas de COR"
            )
        }
    )

    st.subheader("Gráfico de horas estimadas vs. disponibles")
    if not df.empty:
        fig = go.Figure()

        fig.add_trace(go.Bar(
            name='Horas Estimadas',
            x=df["Colaborador"],
            y=df["Horas Estimadas (COR)"],
            marker_color='rgb(25, 40, 150)'
        ))

        fig.add_trace(go.Bar(
            name='Horas Cargadas',
            x=df["Colaborador"],
            y=df["Horas Cargadas (COR)"],
            marker_color='rgb(144, 202, 249)'
        ))

        fig.add_trace(go.Scatter(
            name='Horas Disponibles (c/Buffer)',
            x=df["Colaborador"],
            y=df["Horas Disponibles (c/Buffer)"],
            mode='lines+markers',
            line=dict(color='red', width=3),
            marker=dict(size=8)
        ))

        fig.update_layout(
            height=400,
            margin=dict(t=20),
            yaxis_title='Horas',
            showlegend=True,
            barmode='overlay',
            xaxis=dict(tickangle=45)
        )

        y_max = max(200, df["Horas Disponibles (c/Buffer)"].max() + 10)
        fig.update_yaxes(range=[0, y_max])
        fig.update_traces(opacity=0.75, selector=dict(type='bar'))

        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        **Interpretación del gráfico:**
        - Barras azul oscuro: Horas estimadas para las tareas  
        - Barras azul claro: Horas ya cargadas  
        - Línea roja: Horas disponibles (con buffer)  
        """)

    st.markdown("---")
    st.write("Fin del dashboard. ¡Puedes cambiar de mes en la parte superior!")

################################################################################
# 4. EJECUCIÓN PRINCIPAL
################################################################################
if __name__ == "__main__":
    main()
