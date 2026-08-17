from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    PSEUDOGRAM_API_KEY: str = Field(default="mock-key-for-local-testing")
    DATABASE_URL: str = Field(default="sqlite:///./app.db")
    WEBHOOK_SIGNATURE_REQUIRED: bool = Field(default=True)
    MAX_DM_RETRIES: int = Field(default=5)
    MOCK_API_BASE_URL: str = Field(default="https://pseudogram-api.onrender.com")
    TESTING: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
