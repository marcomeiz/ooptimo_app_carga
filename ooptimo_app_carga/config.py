import os
from pathlib import Path
from dotenv import load_dotenv

class Config:
    @staticmethod
    def load_config():
        """Unified configuration loader that works across different environments"""
        config = {}
        required_vars = [
            'FACTORIAL_API_KEY',
            'FACTORIAL_BASE_URL',
            'COR_API_KEY',
            'COR_CLIENT_SECRET',
            'COR_BASE_URL'
        ]

        # First try: Direct environment variables
        config = {var: os.environ.get(var) for var in required_vars}
        if all(config.values()):
            return config

        # Second try: Streamlit Cloud secrets
        try:
            import streamlit as st
            if hasattr(st, 'secrets') and st.secrets:
                return {key: str(value) for key, value in st.secrets.items()}
        except Exception:
            pass

        # Last try: Local development with .env
        if Path('.env').exists():
            load_dotenv()
            config = {var: os.getenv(var) for var in required_vars}
            if all(config.values()):
                return config

        # If we get here, show what values we actually have
        missing = [var for var in required_vars if not config.get(var)]
        raise ValueError(f"Missing configuration values: {', '.join(missing)}")