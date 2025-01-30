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

        # Production: Try Streamlit Cloud secrets
        try:
            import streamlit as st
            if hasattr(st, 'secrets') and st.secrets:
                return {key: str(value) for key, value in st.secrets.items()}
        except Exception:
            pass

        # Development: Load from .env file
        if Path('.env').exists():
            load_dotenv()

        # Get configuration from environment
        config = {var: os.getenv(var) for var in required_vars}
        if not any(config.values()):
            raise ValueError("No configuration found")

        return config