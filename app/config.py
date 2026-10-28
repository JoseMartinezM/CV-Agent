from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_api_key: str
    gemini_api_key: str = ""
    llm_provider: str = "gemini"
    # lite first: flash only gets 20 free requests a day, lite has more
    llm_model: str = "gemini-3.5-flash-lite"
    # used when the main model is overloaded (503), stuck (504) or out of quota (429)
    llm_fallback_model: str = "gemini-3.5-flash"


settings = Settings()
