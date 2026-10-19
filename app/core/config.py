from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    groq_api_key: str
    redis_url: str = "redis://localhost:6379/0"
    embedding_service_url: str | None = None  # Docker API uses the private worker endpoint.
    document_asset_dir: str = "data/document-assets"
    vision_model: str = "qwen/qwen3.8-27b"
    
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    job_retention_seconds: int = 2_592_000  # 30 days; idempotency keys expire after 24h.
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
