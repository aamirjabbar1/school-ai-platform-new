import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from passlib.hash import bcrypt
from sqlalchemy import select

from config.database import init_db, async_session
from config.settings import PORT, ENV, SCHOOL_NAME, FRONTEND_URL, UPLOAD_DIR, MILVUS_HOST, MILVUS_PORT
from models.models import User

from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.assignments import router as assignments_router
from routes.documents import router as documents_router
from routes.question_papers import router as qp_router
from routes.admin import router as admin_router
from routes.notifications import router as notifications_router


# ─── Rate limiter ─────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ─── Default admin ────────────────────────────────────────────────────────────

async def create_default_admin():
    try:
        async with async_session() as db:
            from sqlalchemy import text
            result = await db.execute(text("SELECT id FROM users WHERE login_id = 'admin001'"))
            if not result.first():
                admin = User(
                    name="System Administrator",
                    login_id="admin001",
                    email="admin@school.edu",
                    password_hash=bcrypt.hash("admin123"),
                    role="admin",
                    is_active=True,
                )
                db.add(admin)
                await db.commit()
                print("[OK] Default admin created: admin001 / admin123")
                print("[!]  IMPORTANT: Change the default admin password immediately!\n")
    except Exception as e:
        print(f"[WARN] Default admin creation (non-fatal): {e}")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # PostgreSQL
    await init_db()

    # Milvus: connect + ensure collection exists (sync calls in thread)
    import asyncio
    from services import vector_service
    try:
        await asyncio.to_thread(vector_service.connect, MILVUS_HOST, MILVUS_PORT)
        await asyncio.to_thread(vector_service.ensure_collection)
        print("[OK] Milvus collection ready.")
    except Exception as exc:
        print(f"[WARN] Milvus init failed (non-fatal, will retry on next request): {exc}")

    await create_default_admin()

    print(f"\n{'='*50}")
    print(f"  School AI Platform — {SCHOOL_NAME}")
    print(f"  Environment : {ENV}")
    print(f"  Docs        : http://localhost:{PORT}/docs")
    print(f"{'='*50}\n")

    yield


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=f"{SCHOOL_NAME} API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve remaining local uploads (submissions still use local filesystem)
os.makedirs(os.path.join(UPLOAD_DIR, "submissions"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    from datetime import datetime
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "school": SCHOOL_NAME,
        "version": "1.0.0",
    }


# ─── Routes ───────────────────────────────────────────────────────────────────

app.include_router(auth_router,          prefix="/api")
app.include_router(chat_router,          prefix="/api")
app.include_router(assignments_router,   prefix="/api")
app.include_router(documents_router,     prefix="/api")
app.include_router(qp_router,            prefix="/api")
app.include_router(admin_router,         prefix="/api")
app.include_router(notifications_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": f"{SCHOOL_NAME} API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "api_base": "/api",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=(ENV == "development"))
