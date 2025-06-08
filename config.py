import os
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict # <-- Import SettingsConfigDict

load_dotenv()

class Settings(BaseSettings):
    """Manages application settings and environment variables."""

    # Define the fields your application ACTUALLY needs
    gemini_api_key: str = Field(..., validation_alias="GEMINI_API_KEY")
    patient_service_base: str = Field(
        "http://localhost:8080", validation_alias="PATIENT_SERVICE_URL"
    )
    appointment_service_base: str = Field(
        "http://localhost:8081", validation_alias="APPOINTMENT_SERVICE_URL"
    )
    debug_mode: bool = Field(False, validation_alias="DEBUG_MODE")

    # Define the model_config to handle settings
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra='ignore'  # <--- THIS IS THE KEY CHANGE! Tell Pydantic to ignore extra vars.
    )

    # Keep your properties
    @property
    def patient_service_v1_url(self) -> str:
        return f"{self.patient_service_base}/v1"

    @property
    def appointment_service_v1_url(self) -> str:
        return f"{self.appointment_service_base}/v1"

# Create a single instance to be used across the application
settings = Settings()

# Validate that the key is present early
if not settings.gemini_api_key:
    raise RuntimeError("GEMINI_API_KEY missing – set it in .env")