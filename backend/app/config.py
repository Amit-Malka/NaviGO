from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    groq_api_key: str
    groq_model: str = "meta-llama/llama-4-maverick-17b-128e-instruct"

    # Google OAuth2
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/api/auth/callback"

    # Amadeus
    amadeus_client_id: str
    amadeus_client_secret: str
    amadeus_hostname: str = "test"

    # App
    frontend_url: str = "http://localhost:5173"
    memory_db_path: str = "./navigo_memory.db"


settings = Settings()
