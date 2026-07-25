from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str = ""
    google_maps_api_key: str = ""
    max_shots: int = 6
    max_tool_calls: int = 15
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
