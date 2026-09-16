import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path, override=False)

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
# Cheaper model for work that is organisation rather than reasoning — class
# summaries from structured data, revision notes, coverage comparison. Spending
# a capable model's rate on those is waste, not quality (spec §19D).
AI_MODEL_FAST = os.getenv("AI_MODEL_FAST", "claude-haiku-4-5")

# Gemini powers document parsing (PDF/DOCX vision extraction).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# ─── Online Classes (LiveKit media server) ────────────────────────────────────
# The key and secret authorise this backend to mint join tokens and control
# rooms. They must never be exposed to a browser — clients only ever receive a
# short-lived token minted server-side.
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")            # wss://live.example.com
LIVEKIT_HTTP_URL = os.getenv("LIVEKIT_HTTP_URL", "")  # https://live.example.com
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
LIVEKIT_TOKEN_TTL_HOURS = int(os.getenv("LIVEKIT_TOKEN_TTL_HOURS", 3))

# ─── Class recordings ─────────────────────────────────────────────────────────
# The recorder runs beside the media server and uploads finished files straight
# to object storage, so recordings never pass through the API container. The
# endpoint must therefore be reachable from the media host, not just from here.
# Recordings are media only: nothing transcribes them, and no AI model reads them.
RECORDING_BUCKET = os.getenv("RECORDING_BUCKET", "class-recordings")
RECORDING_S3_ENDPOINT = os.getenv("RECORDING_S3_ENDPOINT", "")
RECORDING_S3_ACCESS_KEY = os.getenv("RECORDING_S3_ACCESS_KEY", MINIO_ACCESS_KEY)
RECORDING_S3_SECRET_KEY = os.getenv("RECORDING_S3_SECRET_KEY", MINIO_SECRET_KEY)
RECORDING_S3_REGION = os.getenv("RECORDING_S3_REGION", "us-east-1")

# ─── School ───────────────────────────────────────────────────────────────────
SCHOOL_NAME = os.getenv("SCHOOL_NAME", "School AI Platform")
SCHOOL_TAGLINE = os.getenv("SCHOOL_TAGLINE", "Excellence in Education")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# ─── Files ────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 52428800))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
