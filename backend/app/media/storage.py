"""Object storage.

A port with one S3 implementation. The application never imports boto3 outside
this file: swapping MinIO for S3, R2 or a municipal provider's object store is
then a configuration change, which matters because European clubs and councils
do not all get to choose the same one.

Two visibility classes, and the distinction is load-bearing:

  `public/`   site media — crest, hero images, partner logos. It is on the
              club's website by definition, so it is served straight from
              storage with no signing.
  `private/`  everything else — player documents, medical attachments,
              contracts. Never served directly; reached only through a
              short-lived signed URL issued after an authorization check.

There is no code path that promotes a private object to public. Making that a
type-level distinction rather than a runtime flag is what stops a future
"just make it public for now" from quietly exposing a safeguarding document.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import aioboto3
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


_session = aioboto3.Session()


@asynccontextmanager
async def _client() -> AsyncIterator[Any]:
    async with _session.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
    ) as client:
        yield client


def object_key(
    *,
    visibility: Visibility,
    tenant_id: str,
    club_id: str,
    asset_id: str,
    extension: str,
) -> str:
    """The storage key.

    Tenant-first so a bucket listing is scoped by prefix, an export is a prefix
    copy, and an erasure request is a prefix delete. The filename the user
    uploaded never appears: it is attacker-controlled, may contain path
    separators or unicode that breaks tooling, and can itself be personal data
    (`ionut-medical-2019.pdf`). The original name is kept in the database, where
    it is a label rather than an address.
    """
    return f"{visibility.value}/{tenant_id}/{club_id}/{asset_id}.{extension}"


async def put(
    key: str, body: bytes, *, content_type: str, cache_seconds: int = 31_536_000
) -> None:
    """Store an object.

    Public site media is immutable — the key contains a generated id, so a new
    upload is a new key. That is what lets it be cached for a year without a
    stale crest ever surviving a change.
    """
    async with _client() as client:
        await client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl=f"public, max-age={cache_seconds}, immutable",
        )
    log.info("media_stored", key=key, bytes=len(body))


async def delete(key: str) -> None:
    async with _client() as client:
        await client.delete_object(Bucket=settings.s3_bucket, Key=key)
    log.info("media_deleted", key=key)


async def signed_url(key: str, *, expires_seconds: int = 300) -> str:
    """A time-limited URL for a private object.

    Minutes, not days. A signed URL is a bearer token in a query string: it ends
    up in browser history, referrer headers and support tickets, so its value is
    bounded by how quickly it stops working.
    """
    async with _client() as client:
        return str(
            await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket, "Key": key},
                ExpiresIn=expires_seconds,
            )
        )


def public_url(key: str) -> str:
    """The stable, unsigned URL for public site media."""
    base = settings.s3_public_url.rstrip("/")
    return f"{base}/{settings.s3_bucket}/{quote(key)}"


async def ensure_bucket() -> None:
    """Create the bucket and make the `public/` prefix readable.

    Run at startup in development. In production the bucket and its policy are
    infrastructure, not something the application grants itself — the runtime
    credentials there should not carry `PutBucketPolicy` at all.
    """
    import json

    async with _client() as client:
        try:
            await client.head_bucket(Bucket=settings.s3_bucket)
        except Exception:
            await client.create_bucket(Bucket=settings.s3_bucket)
            log.info("media_bucket_created", bucket=settings.s3_bucket)

        # Read-only, and only under `public/`. Everything else stays closed.
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{settings.s3_bucket}/public/*"],
                }
            ],
        }
        await client.put_bucket_policy(Bucket=settings.s3_bucket, Policy=json.dumps(policy))
