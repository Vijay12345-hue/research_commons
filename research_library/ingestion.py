import hashlib
import json
import re
from io import BytesIO

from django.conf import settings
from django.utils import timezone
from minio.error import S3Error
from pypdf import PdfReader

from .models import ResearchIngestion


MAX_PDF_SIZE = 20 * 1024 * 1024  # 20 MB


def extract_pdf_metadata(file_data, resource, checksum, file_size):
    """Extract and normalize metadata from a PDF."""

    reader = PdfReader(BytesIO(file_data), strict=False)
    pdf_info = reader.metadata or {}

    def clean(value):
        if value is None:
            return ""
        return str(value).strip()

    return {
        "resource_id": resource.id,
        "resource_title": clean(resource.title),
        "pdf_title": clean(pdf_info.title),
        "author": clean(pdf_info.author),
        "subject": clean(pdf_info.subject),
        "creator": clean(pdf_info.creator),
        "producer": clean(pdf_info.producer),
        "creation_date": clean(pdf_info.creation_date),
        "modification_date": clean(pdf_info.modification_date),
        "page_count": len(reader.pages),
        "file_format": "PDF",
        "content_type": "application/pdf",
        "file_size_bytes": file_size,
        "checksum_sha256": checksum,
    }


def extract_processed_document(file_data, resource, checksum):
    """Extract and normalize text from each PDF page."""

    reader = PdfReader(BytesIO(file_data), strict=False)
    processed_pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        extracted_text = page.extract_text() or ""

        normalized_text = re.sub(r"[ \t]+", " ", extracted_text)
        normalized_text = re.sub(r" *\n *", "\n", normalized_text)
        normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
        normalized_text = normalized_text.strip()

        processed_pages.append({
            "page_number": page_number,
            "text": normalized_text,
        })

    full_text = "\n\n".join(
        page["text"] for page in processed_pages
    )

    return {
        "resource_id": resource.id,
        "title": str(resource.title).strip(),
        "checksum_sha256": checksum,
        "file_format": "PDF",
        "page_count": len(reader.pages),
        "extracted_pages": processed_pages,
        "total_characters": len(full_text),
        "processing_status": "completed",
    }


def ingest_research_resource(resource):
    """Ingest a PDF and its metadata and processed text into MinIO."""

    if resource.resource_type != "paper":
        raise ValueError("Only paper resources can be ingested.")

    if not resource.file:
        raise ValueError("This research resource has no uploaded PDF.")

    # Read and validate the PDF.
    resource.file.open("rb")
    try:
        file_data = resource.file.read(MAX_PDF_SIZE + 1)
    finally:
        resource.file.close()

    if not file_data:
        raise ValueError("The uploaded PDF is empty.")

    if len(file_data) > MAX_PDF_SIZE:
        raise ValueError("PDF exceeds the 20 MB size limit.")

    if not file_data.startswith(b"%PDF-"):
        raise ValueError("The uploaded file does not have a valid PDF header.")

    # Calculate checksum and file size.
    checksum = hashlib.sha256(file_data).hexdigest()
    file_size = len(file_data)

    # Generate object keys.
    raw_key = f"raw/{checksum}.pdf"
    metadata_key = f"metadata/{checksum}.json"
    processed_key = f"processed/{checksum}.json"

    # Connect to MinIO.
    from .object_storage import get_minio_client

    client = get_minio_client()
    bucket = settings.MINIO_BUCKET

    def object_exists(object_key):
        try:
            client.stat_object(bucket, object_key)
            return True
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return False
            raise

    # Extract metadata and processed text.
    metadata = extract_pdf_metadata(
        file_data=file_data,
        resource=resource,
        checksum=checksum,
        file_size=file_size,
    )

    processed_data = extract_processed_document(
        file_data=file_data,
        resource=resource,
        checksum=checksum,
    )

    # Check whether the three objects already exist.
    raw_exists = object_exists(raw_key)
    metadata_exists = object_exists(metadata_key)
    processed_exists = object_exists(processed_key)

    # Get or create the PostgreSQL ingestion record.
    ingestion, created = ResearchIngestion.objects.get_or_create(
        resource=resource,
        defaults={
            "bucket_name": bucket,
            "object_key": raw_key,
            "checksum_sha256": checksum,
            "file_size": file_size,
            "content_type": "application/pdf",
            "status": "pending",
        },
    )

    # Skip only if everything is already successfully ingested.
    if (
        not created
        and ingestion.checksum_sha256 == checksum
        and ingestion.status == "completed"
        and ingestion.metadata_json == metadata
        and raw_exists
        and metadata_exists
        and processed_exists
    ):
        return ingestion

    # Update ingestion record.
    ingestion.bucket_name = bucket
    ingestion.object_key = raw_key
    ingestion.checksum_sha256 = checksum
    ingestion.file_size = file_size
    ingestion.content_type = "application/pdf"
    ingestion.status = "pending"
    ingestion.error_message = ""
    ingestion.save()

    try:
        # 1. Upload original PDF to raw/.
        if not raw_exists:
            client.put_object(
                bucket_name=bucket,
                object_name=raw_key,
                data=BytesIO(file_data),
                length=file_size,
                content_type="application/pdf",
                metadata={"sha256": checksum},
            )

        # 2. Upload normalized metadata to metadata/.
        metadata_bytes = json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        if not metadata_exists or ingestion.metadata_json != metadata:
            client.put_object(
                bucket_name=bucket,
                object_name=metadata_key,
                data=BytesIO(metadata_bytes),
                length=len(metadata_bytes),
                content_type="application/json",
            )

        # 3. Upload extracted and normalized text to processed/.
        if not processed_exists:
            processed_bytes = json.dumps(
                processed_data,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")

            client.put_object(
                bucket_name=bucket,
                object_name=processed_key,
                data=BytesIO(processed_bytes),
                length=len(processed_bytes),
                content_type="application/json",
            )

        # Mark ingestion as completed in PostgreSQL.
        ingestion.metadata_json = metadata
        ingestion.status = "completed"
        ingestion.ingested_at = timezone.now()
        ingestion.error_message = ""

        ingestion.save(
            update_fields=[
                "metadata_json",
                "status",
                "ingested_at",
                "error_message",
            ]
        )

        return ingestion

    except Exception as exc:
        ingestion.status = "failed"
        ingestion.error_message = str(exc)[:2000]

        ingestion.save(
            update_fields=["status", "error_message"]
        )

        raise