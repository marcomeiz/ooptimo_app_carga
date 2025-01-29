import streamlit as st
import requests
import pandas as pd
import holidays
import plotly.graph_objects as go 
from datetime import datetime, date
from workalendar.europe.spain import Catalonia
from calendar import monthrange
from datetime import timedelta
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

st.set_page_config(
    layout="wide",
    page_title="Dashboard de horas y ausencias"
)

# =============================================================================
# 1. CONFIGURACIONES Y CONSTANTES
# =============================================================================

# -- Configuración de la API de Factorial
FACTORIAL_API_KEY = os.getenv("FACTORIAL_API_KEY")
FACTORIAL_BASE_URL = os.getenv("FACTORIAL_BASE_URL")
HEADERS_FACTORIAL = {
    "accept": "application/json",
    "x-api-key": FACTORIAL_API_KEY,
}

EMPLEADOS_NO_PRODUCTIVOS = {
    "celia henriquez",
    "andrea martínez"
}

# -- Configuración API de COR
API_KEY_COR = os.getenv("COR_API_KEY")
CLIENT_SECRET_COR = os.getenv("COR_CLIENT_SECRET")
BASE_URL_COR = os.getenv("COR_BASE_URL")

# -- Configuración de festivos (España, Barcelona)
festivos_barcelona = holidays.Spain(subdiv="CT")  # Cataluña

# -- Nombres de meses en español
NOMBRES_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]

# -- Diccionario de normalización de nombres
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


# =============================================================================
# 2. FUNCIONES AUXILIARES
# =============================================================================

def normalizar_nombre(nombre):
    """
    Normaliza el nombre del empleado para unificar diferentes versiones.
    """
    nombre_norm = ' '.join(nombre.lower().strip().split())
    return NOMBRE_MAPPING.get(nombre_norm, nombre_norm)

def obtener_tipos_ausencia():
    """Obtiene los tipos de ausencia desde Factorial."""
    url = f"{FACTORIAL_BASE_URL}/resources/timeoff/leave_types"
    response = requests.get(url, headers=HEADERS_FACTORIAL, timeout=10)
    response.raise_for_status()
    tipos = response.json().get('data', [])
    return {tipo['id']: tipo['translated_name'] for tipo in tipos}

def obtener_ausencias():
    """Obtiene todas las ausencias desde Factorial."""
    url = f"{FACTORIAL_BASE_URL}/resources/timeoff/leaves"
    response = requests.get(url, headers=HEADERS_FACTORIAL, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data.get('data', [])

def calcular_dias_laborables_por_mes(inicio, fin):
    """
    Calcula los días laborables por mes (excluyendo sábados, domingos y festivos).
    Retorna un Series de pandas con el conteo de días por Período (YYYY-MM).
    """
    dias = pd.date_range(start=inicio, end=fin, freq='B')  # 'B' -> solo días laborables (L-V)
    dias_laborables = dias[~dias.isin(festivos_barcelona)]  # Excluir festivos (festivos_barcelona)

    # Agrupar por mes y contar
    dias_por_mes = dias_laborables.to_series().groupby(dias_laborables.to_period("M")).size()
    return dias_por_mes

def obtener_token_cor(api_key, client_secret):
    """
    Obtiene el token de acceso usando client_credentials en COR.
    """
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
        print("Error al obtener el token:", resp.status_code, resp.text)
        return None

def obtener_tareas_cor(access_token, page=1, per_page=10):
    """
    Obtiene las tareas de COR, paginadas. Retorna el JSON con la respuesta.
    """
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

def calcular_ausencias_empleado(empleado_nombre, anio, mes):
    """
    Calcula los días de ausencia de un empleado para un mes específico,
    diferenciando entre vacaciones, otras ausencias y 'teletrabajo extra' que no descuenta horas.
    """
    all_ausencias = obtener_ausencias()
    dias_vacaciones = 0
    dias_otras_ausencias = 0
    dias_teletrabajo = 0  # Ausencias que no afectan a horas disponibles

    # IDs de ausencia que NO descuentan (ejemplo: día extra teletrabajo)
    ids_no_descuentan = {2280065}  # Ajustar a tus IDs reales en Factorial
    ID_VACACIONES = 2276680        # Ajustar a tu ID de "Vacaciones"

    empleado_nombre_norm = normalizar_nombre(empleado_nombre)

    for ausencia in all_ausencias:
        nombre_ausencia = normalizar_nombre(ausencia.get("employee_full_name", ""))
        if nombre_ausencia != empleado_nombre_norm:
            continue

        inicio = pd.to_datetime(ausencia["start_on"])
        fin = pd.to_datetime(ausencia["finish_on"])

        # Verificamos que caiga en el mes/año especificado
        # (Esta lógica asume que la ausencia empieza y termina en el mismo mes;
        # si atraviesa meses, podríamos necesitar un ajuste más elaborado)
        if (inicio.year == anio and inicio.month == mes):
            dias = calcular_dias_laborables_por_mes(inicio, fin)
            # Días del mes (ej. 2025-01)
            clave_mes = pd.Period(f"{anio}-{mes:02d}")
            if clave_mes in dias.index:
                total_dias = dias[clave_mes]
            else:
                total_dias = 0

            tipo_id = ausencia.get("leave_type_id")

            if tipo_id in ids_no_descuentan:
                dias_teletrabajo += total_dias
            elif tipo_id == ID_VACACIONES:
                dias_vacaciones += total_dias
            else:
                dias_otras_ausencias += total_dias

    return dias_vacaciones, dias_otras_ausencias, dias_teletrabajo

def calcular_dias_laborables_festivos(year, month):
    """
    Devuelve (dias_laborables, festivos_laborables) para un 'year' y 'month' en Cataluña.
    Se apoya en la librería workalendar.europe.spain.Catalonia.
    """
    cal = Catalonia()
    _, total_days = monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    # Días laborables (lun-vie)
    dias_laborables = 0
    for day in range(1, total_days + 1):
        current_date = date(year, month, day)
        if current_date.weekday() < 5:
            dias_laborables += 1

    # Contamos festivos oficiales que caen en días laborables
    festivos_laborables = 0
    holidays_year = cal.holidays(year)
    for dia, _ in holidays_year:
        if start_date <= dia <= end_date and dia.weekday() < 5:
            festivos_laborables += 1

    return dias_laborables - festivos_laborables, festivos_laborables

def calcular_horas_disponibles(year, month, dias_vacaciones, dias_otras_ausencias=0, buffer_porcentaje=0.1):
    """
    Calcula horas disponibles reales tras restar vacaciones, otras ausencias, festivos y un buffer de seguridad.
    - Por convención, en agosto se asumen 7h/día, en otros meses 8h/día.
    - `dias_otras_ausencias` se descuenta al mismo ritmo que vacaciones.
    """
    dias_laborables, _ = calcular_dias_laborables_festivos(year, month)
    horas_por_dia = 7 if month == 8 else 8

    horas_brutas = dias_laborables * horas_por_dia
    horas_vacaciones = dias_vacaciones * horas_por_dia
    horas_ausencias = dias_otras_ausencias * horas_por_dia

    buffer = horas_brutas * buffer_porcentaje
    horas_disponibles = horas_brutas - horas_vacaciones - horas_ausencias - buffer
    return horas_disponibles


# =============================================================================
# 3. LÓGICA PRINCIPAL: DESCARGA DE DATOS DE FACTORIAL Y COR
# =============================================================================

@st.cache_data(show_spinner=True)
def descargar_datos():
    """
    Descarga las tareas de COR (paginar), las ausencias y tipos de ausencia de Factorial,
    y construye la estructura final (dict) empleadosPorMes con horas y ausencias.
    """
    # 3.1 Conectamos con COR
    access_token = obtener_token_cor(API_KEY_COR, CLIENT_SECRET_COR)
    if not access_token:
        st.error("No se pudo obtener el token de COR. Revisa las credenciales.")
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

        # Filtramos las tareas con 'hour_charged' > 0 o 'estimated' > 0
        filtered = [t for t in tasks if (t.get("hour_charged", 0) > 0 or t.get("estimated", 0) > 0)]
        all_tasks.extend(filtered)

        page += 1

    # 3.2 Construimos la estructura empleadosPorMes
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

        # Distribución equitativa de horas/estimado entre colaboradores
        hc_por_colab = hour_charged / num_cols
        est_por_colab = estimated_hours / num_cols

        for colab in colaboradores:
            raw_name = f"{colab.get('first_name','')} {colab.get('last_name','')}".strip()
            colab_name = normalizar_nombre(raw_name)

            if colab_name not in empleadosPorMes[sheet_name]:
                empleadosPorMes[sheet_name][colab_name] = {
                    "horas_cargadas": 0.0,
                    "horas_estimadas": 0.0,
                    "vacaciones": 0,          # días
                    "otras_ausencias": 0,    # días
                    "teletrabajo": 0         # días
                }

            empleadosPorMes[sheet_name][colab_name]["horas_cargadas"] += hc_por_colab
            empleadosPorMes[sheet_name][colab_name]["horas_estimadas"] += est_por_colab

    # 3.3 Para cada (mes-año, colaborador), calculamos ausencias en Factorial
    #     y actualizamos "vacaciones", "otras_ausencias" y "teletrabajo"
    for sheet_name, colaboradores in empleadosPorMes.items():
        try:
            mes_nombre, anio_str = sheet_name.split("-")
            anio = int(anio_str)
            mes = NOMBRES_MESES.index(mes_nombre) + 1

            for colaborador in colaboradores.keys():
                vac, otras, tele = calcular_ausencias_empleado(colaborador, anio, mes)
                empleadosPorMes[sheet_name][colaborador]["vacaciones"] = vac
                empleadosPorMes[sheet_name][colaborador]["otras_ausencias"] = otras
                empleadosPorMes[sheet_name][colaborador]["teletrabajo"] = tele

        except Exception as e:
            print(f"Error procesando {sheet_name}: {e}")

    return empleadosPorMes

# =============================================================================
# 4. CONSTRUCCIÓN DEL DASHBOARD
# =============================================================================

def main():
    st.title("Dashboard de horas y ausencias (Factorial + COR)")
    
    # Add refresh button with normal width
    st.button("🔄 Actualizar Datos", help="Forzar actualización de datos de COR y Factorial")
    
    st.markdown("---")

    # 4.1 Descarga o cachea los datos
    with st.spinner("Descargando datos de COR y Factorial..."):
        empleados_data = descargar_datos()
    
    if not empleados_data:
        st.warning("No se encontró información de tareas o el proceso falló.")
        return

    # 4.2 Selección de mes-año
    todos_los_meses = sorted(list(empleados_data.keys()), key=lambda x: (
        int(x.split("-")[1]),  # año
        NOMBRES_MESES.index(x.split("-")[0])  # orden del mes
    ))
    
    # Get current month-year
    current_month = NOMBRES_MESES[datetime.now().month - 1]
    current_year = datetime.now().year
    current_month_year = f"{current_month}-{current_year}"
    
    # Find current month index
    try:
        current_index = todos_los_meses.index(current_month_year)
        # Calculate range: 3 months back and 1 month forward
        start_index = max(0, current_index - 3)
        end_index = min(len(todos_los_meses), current_index + 2)
        meses_mostrados = todos_los_meses[start_index:end_index]
        # Adjust default index for the filtered list
        default_index = meses_mostrados.index(current_month_year) if current_month_year in meses_mostrados else 0
    except ValueError:
        # If current month not found, show last 5 months
        meses_mostrados = todos_los_meses[-5:] if len(todos_los_meses) > 5 else todos_los_meses
        default_index = len(meses_mostrados) - 1
    
    # Add custom CSS for date picker style
    st.markdown("""
        <style>
        div[data-testid="stSelectbox"] {
            max-width: 200px;
            margin: 0 auto;
        }
        </style>
    """, unsafe_allow_html=True)
    
    mes_seleccionado = st.selectbox(
        "Selecciona un mes/año para analizar:",
        options=meses_mostrados,
        index=default_index,
        label_visibility="collapsed"
    )

    # After month selection
    colaboradores_mes = empleados_data.get(mes_seleccionado, {})
    if not colaboradores_mes:
        st.info(f"No hay colaboradores con horas en {mes_seleccionado}")
        return

    # Calculate common data first
    mes_nombre, anio_str = mes_seleccionado.split("-")
    anio = int(anio_str)
    mes_num = NOMBRES_MESES.index(mes_nombre) + 1

    dias_laborables, festivos_laborables = calcular_dias_laborables_festivos(anio, mes_num)
    horas_por_dia = 7 if mes_num == 8 else 8
    horas_mes_brutas = dias_laborables * horas_por_dia

    # Now display the cards with the calculated data
    col1, col2, col3 = st.columns(3)
    
    metrics_style = """
    <style>
        div[data-testid="stHorizontalBlock"] > div div[data-testid="stMarkdownContainer"] {
            background-color: #f8f9fa;
            padding: 1em;
            border-radius: 10px;
            height: 100%;
            text-align: center;
        }
    </style>
    """
    st.markdown(metrics_style, unsafe_allow_html=True)
    
    with col1:
        st.markdown(f"""
        <h3 style='margin:0;font-size:1.2em;text-align:center;'>📅 Días laborables</h3>
        <p style='font-size:2em;font-weight:bold;margin:0.5em 0;text-align:center;'>{dias_laborables}</p>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <h3 style='margin:0;font-size:1.2em;text-align:center;'>🎉 Festivos laborables</h3>
        <p style='font-size:2em;font-weight:bold;margin:0.5em 0;text-align:center;'>{festivos_laborables}</p>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <h3 style='margin:0;font-size:1.2em;text-align:center;'>⏰ Horas por día</h3>
        <p style='font-size:2em;font-weight:bold;margin:0.5em 0;text-align:center;'>{horas_por_dia}</p>
        """, unsafe_allow_html=True)

    # Add summary metrics
    st.markdown("### Resumen del mes")
    
    # Calculate totals
    total_horas_disponibles = sum(calcular_horas_disponibles(anio, mes_num, 
                                                           info.get("vacaciones", 0),
                                                           info.get("otras_ausencias", 0),
                                                           buffer_porcentaje=0.1)
                                 for colab, info in colaboradores_mes.items()
                                 if normalizar_nombre(colab) not in EMPLEADOS_NO_PRODUCTIVOS)
    
    total_horas_estimadas = sum(info.get("horas_estimadas", 0) 
                               for colab, info in colaboradores_mes.items()
                               if normalizar_nombre(colab) not in EMPLEADOS_NO_PRODUCTIVOS)
    
    total_horas_cargadas = sum(info.get("horas_cargadas", 0) 
                              for colab, info in colaboradores_mes.items()
                              if normalizar_nombre(colab) not in EMPLEADOS_NO_PRODUCTIVOS)
    
    # Display metrics in columns
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            label="Total Horas Disponibles",
            value=f"{total_horas_disponibles:.1f}h",
            help="Suma de las horas disponibles de todos los colaboradores (con buffer)"
        )
    
    with col2:
        st.metric(
            label="Total Horas Estimadas",
            value=f"{total_horas_estimadas:.1f}h",
            help="Suma de las horas estimadas en COR"
        )
    
    with col3:
        st.metric(
            label="Total Horas Cargadas",
            value=f"{total_horas_cargadas:.1f}h",
            help="Suma de las horas ya cargadas en COR"
        )

    # Continue with data processing for the table
    data_rows = []
    for colaborador, info in colaboradores_mes.items():
        # Skip non-productive employees
        if any(no_prod in normalizar_nombre(colaborador) for no_prod in EMPLEADOS_NO_PRODUCTIVOS):
            continue
            
        v = info.get("vacaciones", 0)
        oa = info.get("otras_ausencias", 0)
        tele = info.get("teletrabajo", 0)
        
        # Cálculo personalizado de horas disponibles
        horas_disp = calcular_horas_disponibles(anio, mes_num, v, oa, buffer_porcentaje=0.1)
        hc = info.get("horas_cargadas", 0)
        he = info.get("horas_estimadas", 0)

        pct_est = 0
        if horas_disp > 0:
            pct_est = (he / horas_disp) * 100

        data_rows.append({
            "Colaborador": colaborador,
            "Vacaciones (días)": v,
            "Otras ausencias (días)": oa,
            "Teletrabajo (días)": tele,
            "Horas brutas mes": round(horas_mes_brutas, 1),
            "Horas Cargadas (COR)": round(hc, 1),
            "Horas Estimadas (COR)": round(he, 1),
            "Horas Disponibles (c/Buffer)": round(horas_disp, 1),
            "Carga %": min(pct_est, 100)
        })
    
    # Create table with full width
    df = pd.DataFrame(data_rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=(len(df) + 1) * 35,
        column_config={
            "Carga %": st.column_config.ProgressColumn(
                "Carga %",
                help="Porcentaje de horas estimadas respecto a las disponibles",
                format="%d%%",
                min_value=0,
                max_value=100,
            )
        }
    )

    # 4.4 Visualización gráfica
    st.subheader("Gráfico de horas estimadas vs. disponibles")
    if not df.empty:
        fig = go.Figure()
        
        # Add bars for estimated hours (bottom layer)
        fig.add_trace(go.Bar(
            name='Horas Estimadas',
            x=df["Colaborador"],
            y=df["Horas Estimadas (COR)"],
            marker_color='rgb(25, 40, 150)'  # Dark blue color
        ))
        
        # Add bars for charged hours (overlay)
        fig.add_trace(go.Bar(
            name='Horas Cargadas',
            x=df["Colaborador"],
            y=df["Horas Cargadas (COR)"],
            marker_color='rgb(144, 202, 249)'  # Light blue color
        ))
        
        # Add the line for available hours with markers
        fig.add_trace(go.Scatter(
            name='Horas Disponibles (c/Buffer)',
            x=df["Colaborador"],
            y=df["Horas Disponibles (c/Buffer)"],
            mode='lines+markers',
            line=dict(color='red', width=3),
            marker=dict(size=8)
        ))
        
        # Update layout with fixed y-axis range and overlay bars
        fig.update_layout(
            height=400,
            margin=dict(t=20),
            yaxis_title='Horas',
            showlegend=True,
            barmode='overlay',  # This makes bars overlay each other
            yaxis=dict(
                range=[0, 200],
                dtick=20,
            ),
            xaxis=dict(
                tickangle=45
            )
        )
        
        # Make bars semi-transparent for better overlay visualization
        fig.update_traces(opacity=0.75, selector=dict(type='bar'))
        
        # Display the plot
        st.plotly_chart(fig, use_container_width=True)
        
        # Updated explanation
        st.markdown("""
        **Interpretación del gráfico:**
        - Barras azul oscuro: Horas estimadas para las tareas
        - Barras azul claro: Horas ya cargadas
        - Línea roja: Horas disponibles del mes (con buffer)
        """)

    st.markdown("---")
    st.write("Fin del dashboard. Puedes cambiar de mes en la parte superior.")

if __name__ == "__main__":
    main()
