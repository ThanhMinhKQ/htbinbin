import os
import logging
from dotenv import load_dotenv

load_dotenv()  # load biến từ .env

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set!")

# Fix prefix nếu copy nhầm postgres:// -> postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Đảm bảo sử dụng driver 'psycopg' (v3) đã được cài, thay vì 'psycopg2' mặc định.
if "postgresql+psycopg2://" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
elif "postgresql://" in DATABASE_URL and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# Thêm sslmode=require cho kết nối Supabase pooler để đảm bảo kết nối an toàn
# và tránh lỗi "server closed the connection unexpectedly".
if "pooler.supabase.com" in DATABASE_URL and "sslmode" not in DATABASE_URL:
    separator = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL += f"{separator}sslmode=require"

SMTP_CONFIG = {
    "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
    "port": int(os.getenv("SMTP_PORT", 587)),
    "user": os.getenv("SMTP_USER", ""),
    "password": os.getenv("SMTP_PASSWORD", ""),
}

ALERT_EMAIL = os.getenv("ALERT_EMAIL", "yourmail@example.com")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("binbin-app")
