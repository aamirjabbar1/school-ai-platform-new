"""
MinIO object storage service.

All public functions are synchronous (minio SDK is sync).
Call them with `await asyncio.to_thread(fn, ...)` from async FastAPI handlers.
In Celery tasks (sync context) call them directly.
"""
import io
from minio import Minio
from minio.error import S3Error

from config.settings import MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET, MINIO_SECURE

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
    return _client


def ensure_bucket(bucket: str = MINIO_BUCKET) -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(object_name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client = get_client()
    ensure_bucket()
    client.put_object(
        MINIO_BUCKET,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def download_file(object_name: str) -> bytes:
    client = get_client()
    response = client.get_object(MINIO_BUCKET, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_file(object_name: str) -> None:
    try:
        get_client().remove_object(MINIO_BUCKET, object_name)
    except S3Error:
        pass


def get_presigned_url(object_name: str, expires_seconds: int = 3600) -> str:
    from datetime import timedelta
    return get_client().presigned_get_object(
        MINIO_BUCKET,
        object_name,
        expires=timedelta(seconds=expires_seconds),
    )


def make_object_name(document_id: str, safe_filename: str) -> str:
    """Canonical object name for a document file."""
    return f"documents/{document_id}/{safe_filename}"
