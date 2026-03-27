"""
S3Service — all document storage operations for the demographics agent.
Documents are stored at a canonical key path:
  {env}/{clinic_id}/{patient_id}/{document_type}/{document_id}/{filename}
"""
from __future__ import annotations

import hashlib
import io
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


class S3Service:
    def __init__(self) -> None:
        settings = get_settings()
        self.default_bucket = settings.s3_document_bucket
        self.env = settings.app_env

        kwargs: dict[str, Any] = {"region_name": settings.aws_region}
        if settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self.client = boto3.client("s3", **kwargs)

    # ── Key helpers ───────────────────────────────────────────────────────────

    def build_key(
        self,
        clinic_id: int,
        patient_id: int,
        document_type: str,
        document_id: int | str,
        filename: str,
    ) -> str:
        return (
            f"{self.env}/{clinic_id}/{patient_id}"
            f"/{document_type.lower()}/{document_id}/{filename}"
        )

    # ── Core operations ───────────────────────────────────────────────────────

    def head_object(self, bucket: str, key: str) -> dict:
        """Verify that an object exists and return its metadata."""
        return self.client.head_object(Bucket=bucket, Key=key)

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def get_bytes(self, bucket: str, key: str) -> bytes:
        """Download an object and return raw bytes."""
        log.info("s3.get_bytes", bucket=bucket, key=key)
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> str:
        """Upload bytes and return the S3 key."""
        log.info("s3.put_object", bucket=bucket, key=key, size=len(data))
        kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        if metadata:
            kwargs["Metadata"] = {k: str(v) for k, v in metadata.items()}
        self.client.put_object(**kwargs)
        return key

    def delete_object(self, bucket: str, key: str) -> None:
        self.client.delete_object(Bucket=bucket, Key=key)

    def presigned_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
        operation: str = "get_object",
    ) -> str:
        """Generate a pre-signed URL for download (get_object) or upload (put_object)."""
        return self.client.generate_presigned_url(
            operation,
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def presigned_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str = "application/pdf",
        expires_in: int = 900,
    ) -> dict:
        """Return a pre-signed POST envelope for browser/app direct upload."""
        return self.client.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, 20_000_000],  # 20 MB cap
            ],
            ExpiresIn=expires_in,
        )

    def copy_object(
        self,
        src_bucket: str,
        src_key: str,
        dst_bucket: str,
        dst_key: str,
    ) -> None:
        self.client.copy_object(
            CopySource={"Bucket": src_bucket, "Key": src_key},
            Bucket=dst_bucket,
            Key=dst_key,
        )

    # ── Checksum helper ───────────────────────────────────────────────────────

    @staticmethod
    def sha256_hex(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    # ── Convenience: download to a BytesIO for OCR ───────────────────────────

    def get_fileobj(self, bucket: str, key: str) -> io.BytesIO:
        buf = io.BytesIO()
        self.client.download_fileobj(bucket, key, buf)
        buf.seek(0)
        return buf

    # ── List document keys by prefix ─────────────────────────────────────────

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
