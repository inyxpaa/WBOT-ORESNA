"""
app/core/config.py - Configuración centralizada del bot ORESNA
Carga todas las variables de entorno desde .env
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # WhatsApp Cloud API
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    PHONE_NUMBER_ID: str = os.getenv("PHONE_NUMBER_ID", "")
    VERIFY_TOKEN: str = os.getenv("VERIFY_TOKEN", "oresna_bot_verify_2024")

    # Google Gemini (IA gratuita)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Número del jefe para alertas (formato internacional sin +)
    BOSS_PHONE: str = os.getenv("BOSS_PHONE", "")

    # Ruta al catálogo de propiedades
    CATALOG_PATH: str = os.getenv("CATALOG_PATH", "data/propiedades.csv")


settings = Settings()
