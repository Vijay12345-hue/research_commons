
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from minio import Minio


def get_minio_client():
    """
    Create and return a MinIO client using Django settings.
    """

    if not settings.MINIO_ACCESS_KEY or not settings.MINIO_SECRET_KEY:
        raise ImproperlyConfigured(
            "MinIO access credentials are missing from .env"
        )

    return Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def verify_minio_bucket():
    """
    Verify that Django can connect to MinIO
    and access the research bucket.
    """

    client = get_minio_client()
    bucket = settings.MINIO_BUCKET

    if not client.bucket_exists(bucket):
        raise RuntimeError(
            f"MinIO bucket '{bucket}' does not exist."
        )

    return {
        "connected": True,
        "bucket": bucket,
        "exists": True,
    }
