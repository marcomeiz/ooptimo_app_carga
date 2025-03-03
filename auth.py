import streamlit as st

def check_auth():
    """Verifica si el usuario está autenticado con una cuenta @ooptimo.com"""
    # Esta variable solo existe cuando la app está desplegada en Streamlit Cloud
    if not hasattr(st, 'experimental_user'):
        return False
        
    user = st.experimental_user
    if not user or not user.email:
        return False
        
    return user.email.endswith('@ooptimo.com')

def show_login():
    """Muestra la página de login"""
    st.title("🔒 Acceso Restringido")
    st.warning("Esta aplicación es solo para empleados de Ooptimo")
    st.info("Por favor, inicia sesión con tu cuenta de Google (@ooptimo.com)")