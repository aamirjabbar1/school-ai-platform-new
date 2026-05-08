import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend-python directory regardless of cwd
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path, override=True)

PORT = int(os.getenv("PORT", 5000))
ENV = os.getenv("ENV", "development")
JWT_SECRET = os.getenv("JWT_SECRET", "change_me")
JWT_EXPIRES_DAYS = int(os.getenv("JWT_EXPIRES_DAYS", 7))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-opus-4-6")
SCHOOL_NAME = os.getenv("SCHOOL_NAME", "School AI Platform")
SCHOOL_TAGLINE = os.getenv("SCHOOL_TAGLINE", "Excellence in Education")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 52428800))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
