import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "RevenueOS"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./revenueos.db")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")
    
    # Razorpay Credentials & Mode (Backend Only - Test Mode Enforced)
    RAZORPAY_MODE: str = os.getenv("RAZORPAY_MODE", "test").lower()
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "rzp_test_placeholder_key")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "rzp_test_placeholder_secret")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "rzp_webhook_secret_placeholder")

    # Production Security, Auth & Rate Limiting (Stage 7)
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "revenueos_jwt_secure_secret_key_2026_test_mode")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    RATE_LIMIT_PER_MINUTE: int = 120
    MAX_REQUEST_SIZE_BYTES: int = 1048576  # 1 MB maximum request payload
    ALLOWED_ORIGINS: list = ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"]
    ENFORCE_AUTH: bool = os.getenv("ENFORCE_AUTH", "false").lower() in ("true", "1", "yes")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_safety(self) -> None:
        """Enforces test-mode security constraints at startup."""
        if self.RAZORPAY_MODE != "test":
            raise ValueError(
                f"FATAL: RAZORPAY_MODE is set to '{self.RAZORPAY_MODE}'. "
                f"RevenueOS prototype strictly enforces 'test' mode. Production mode is prohibited."
            )
        if self.RAZORPAY_KEY_ID.startswith("rzp_live_"):
            raise ValueError(
                "FATAL: Production Razorpay credentials ('rzp_live_...') detected. "
                "Live mode execution is strictly prohibited. Use test credentials ('rzp_test_...')."
            )

settings = Settings()
settings.validate_safety()

