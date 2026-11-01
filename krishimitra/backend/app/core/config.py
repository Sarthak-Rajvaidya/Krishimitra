from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    brand_name: str = "KrishiMitra"
    app_env: str = "development"
    secret_key: str = "dev-only-insecure-key-change-me"
    access_token_expire_minutes: int = 60
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173"

    database_url: str = "sqlite:///./krishimitra_dev.db"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "krishi_knowledge"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    rag_min_score: float = 0.25        # cosine relevance gate; tune per embedder via the retrieval-test page
    embedding_backend: str = "hash"  # "hash" (offline) | "sentence-transformers"

    llm_provider_order: str = "groq,mistral,gemini"
    llm_timeout_seconds: float = 20
    llm_max_retries: int = 1
    llm_cooldown_seconds: int = 60
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    upload_dir: str = "./storage/uploads"
    max_upload_mb: int = 8
    knowledge_dir: str = "./storage/knowledge"

    model_artifact_dir: str = "./ml/artifacts"
    min_confidence_for_display: float = 0.5

    demo_password: str = ""

    # --- security ---
    data_encryption_key: str = ""         # Fernet key (urlsafe base64, 32 bytes). REQUIRED in production.
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_dev_echo: bool = False            # return OTP in API response (development/test only!)
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    session_days: int = 7
    db_pool_size: int = 10               # per API process; total connections = workers x (pool_size + max_overflow)
    db_max_overflow: int = 10
    redis_url: str = ""                   # optional: shared rate-limit counters + cache across API instances

    # --- external providers (all optional; features degrade honestly when unset) ---
    sms_provider: str = "console"         # console | twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@krishimitra.local"
    push_provider: str = "none"           # none (FCM adapter not wired in this build)
    payment_provider: str = "simulated"   # simulated | razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    weather_provider: str = "open-meteo"
    weather_cache_seconds: int = 900

    # --- business rules ---
    commission_bp: int = 500              # platform commission on supplier sales (basis points)
    delivery_partner_fee_paise: int = 3000
    delivery_due_hours: int = 48
    iot_offline_minutes: int = 20
    iot_raw_retention_days: int = 30
    gateway_max_topup_paise: int = 5_000_000
    rate_limit_multiplier: int = 1   # tests set high; keep 1 in real deployments

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
