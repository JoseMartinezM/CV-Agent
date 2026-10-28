from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_api_key: str
    gemini_api_key: str = ""
    llm_provider: str = "gemini"
    llm_model: str = "gemini-flash-latest"


settings = Settings()
