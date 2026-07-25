from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    gemini_api_key: str = ""
    google_maps_api_key: str = ""
    max_shots: int = 6
    max_tool_calls: int = 15
    class Config:
        env_file = ".env"

settings = Settings()
