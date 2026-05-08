import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path, override=True)

ENV = os.getenv("ENV", "development")
PORT = int(os.getenv("PORT", 8000))

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/school_ai_db",
)
SYNC_DATABASE_URL = os.getenv(
    "SYNC_DATABASE_URL",
    DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://"),
)

# ─── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ─── MinIO object storage ─────────────────────────────────────────────────────
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "school-documents")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

# ─── Milvus vector database ───────────────────────────────────────────────────
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", 19530))

# ─── Auth ─────────────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "change_me")
JWT_EXPIRES_DAYS = int(os.getenv("JWT_EXPIRES_DAYS", 7))

# ─── AI ───────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-opus-4-6")

# ─── School ───────────────────────────────────────────────────────────────────
SCHOOL_NAME = os.getenv("SCHOOL_NAME", "School AI Platform")
SCHOOL_TAGLINE = os.getenv("SCHOOL_TAGLINE", "Excellence in Education")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# ─── Files ────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 52428800))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
