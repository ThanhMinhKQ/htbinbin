import os

DATABASE_URL = os.getenv("DATABASE_URL")

# fallback cho local development
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./test.db"

# Fix prefix nếu copy nhầm postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

SMTP_CONFIG = {
    "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
    "port": int(os.getenv("SMTP_PORT", 587)),
    "user": os.getenv("SMTP_USER", ""),
    "password": os.getenv("SMTP_PASSWORD", ""),
}

ALERT_EMAIL = os.getenv("ALERT_EMAIL", "yourmail@example.com")
