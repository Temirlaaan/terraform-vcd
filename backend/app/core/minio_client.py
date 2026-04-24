"""Thin S3 wrapper around boto3 for MinIO version snapshots.

Lives separate from terraform's S3 backend (which speaks S3 directly).
Used by ``version_store`` to upload/download/delete HCL and state files
under ``deployments/<id>/v<N>/``.

boto3 is sync; calls are dispatched via ``asyncio.to_thread`` so the
event loop is not blocked.
"""

from __future__ import annotations

import asyncio
import logging
import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _build_client():
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


_BUCKET = os.environ.get("TF_STATE_BUCKET", "terraform-state")


async def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    def _do():
        client = _build_client()
        client.put_object(Bucket=_BUCKET, Key=key, Body=data, ContentType=content_type)
    await asyncio.to_thread(_do)


async def put_text(key: str, text: str, content_type: str = "text/plain") -> None:
    await put_bytes(key, text.encode("utf-8"), content_type=content_type)


async def get_bytes(key: str) -> bytes:
    def _do() -> bytes:
        client = _build_client()
        resp = client.get_object(Bucket=_BUCKET, Key=key)
        return resp["Body"].read()
    return await asyncio.to_thread(_do)


async def get_text(key: str) -> str:
    raw = await get_bytes(key)
    return raw.decode("utf-8")


async def delete_key(key: str) -> None:
    def _do():
        client = _build_client()
        try:
            client.delete_object(Bucket=_BUCKET, Key=key)
        except ClientError as exc:
            logger.warning("delete_object %s failed: %s", key, exc)
    await asyncio.to_thread(_do)


async def copy_key(src_key: str, dst_key: str) -> None:
    def _do():
        client = _build_client()
        client.copy_object(
            Bucket=_BUCKET,
            CopySource={"Bucket": _BUCKET, "Key": src_key},
            Key=dst_key,
        )
    await asyncio.to_thread(_do)


async def exists(key: str) -> bool:
    def _do() -> bool:
        client = _build_client()
        try:
            client.head_object(Bucket=_BUCKET, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
    return await asyncio.to_thread(_do)


def bucket_name() -> str:
    return _BUCKET
