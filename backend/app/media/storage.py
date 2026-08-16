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
from aiobotocore.config import AioConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.errors import StorageUnavailable

log = structlog.get_logger(__name__)


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


_session = aioboto3.Session()


@asynccontextmanager
async def _client() -> AsyncIterator[Any]:
    config = AioConfig(
        # SigV4 explicitly: some S3-compatible gateways still advertise SigV2
        # and negotiate down to it, and a presigned URL signed the old way is
        # rejected by anything modern in front of them.
        signature_version="s3v4",
        s3={"addressing_style": settings.s3_addressing_style},
        retries={"max_attempts": 3, "mode": "standard"},
        # Seconds, not the default minute apiece. A misconfigured bucket
        # answers immediately, but an endpoint that does not resolve does not
        # answer at all — and the club is left watching a spinner for over a
        # minute before being told "something went wrong". Fail while they are
        # still looking at the screen.
        connect_timeout=5,
        read_timeout=20,
        # Botocore began sending every upload as `aws-chunked` with a CRC32
        # trailer, and validating one on the way back. Amazon understands it;
        # most S3-compatible gateways do not, and reject the request with
        # `MissingContentLength` — a message that points at a header we did
        # send, for a body encoded in a way they cannot read.
        #
        # `when_required` keeps checksums where the operation genuinely needs
        # one and sends a plain body otherwise, which is what every
        # implementation has understood for fifteen years.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_supported",
    )
    async with _session.client(
        "s3",
        # `or None` matters: an empty endpoint has to become *absent*, not an
        # empty string, or boto tries to reach "" instead of resolving Amazon's
        # regional endpoint.
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=config,
    ) as client:
        yield client


@asynccontextmanager
async def _translated(operation: str, key: str) -> AsyncIterator[None]:
    """Turn a storage failure into something an operator can act on.

    Uncaught, a missing bucket reaches the browser as an opaque 500 and the
    reason is thirty lines into a traceback. The three that actually happen —
    `NoSuchBucket`, `AccessDenied`, `SignatureDoesNotMatch` — are all
    configuration, and all say plainly what is wrong once you can see the code.
    """
    try:
        yield
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        log.error(
            "media_storage_failed",
            operation=operation,
            key=key,
            code=code,
            bucket=settings.s3_bucket,
            endpoint=settings.s3_endpoint_url,
            region=settings.s3_region,
        )
        raise StorageUnavailable(
            {
                "NoSuchBucket": f"The bucket {settings.s3_bucket!r} does not exist.",
                "AccessDenied": "The storage key is not allowed to write here.",
                "SignatureDoesNotMatch": (
                    "Storage rejected the signature — usually the wrong region."
                ),
            }.get(code, f"Storage refused the request ({code}).")
        ) from exc
    except BotoCoreError as exc:
        # Connection, DNS, timeout: no HTTP response at all, so no error code.
        log.error(
            "media_storage_unreachable",
            operation=operation,
            key=key,
            endpoint=settings.s3_endpoint_url,
            error=str(exc),
        )
        raise StorageUnavailable("File storage did not respond.") from exc


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
    async with _client() as client, _translated("put", key):
        await client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl=f"public, max-age={cache_seconds}, immutable",
        )
    log.info("media_stored", key=key, bytes=len(body))


async def delete(key: str) -> None:
    async with _client() as client, _translated("delete", key):
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
    """The stable, unsigned URL for public site media.

    `S3_PUBLIC_URL` is the base a key hangs directly off — bucket included
    where the provider expects it in the path. This used to append the bucket
    itself, which is right for exactly one of the three shapes in use:
    path-style (`host/bucket/key`, MinIO and most OpenStack gateways),
    virtual-hosted (`bucket.host/key`, Amazon and R2), and a CDN domain in
    front of either, where the bucket does not appear at all.
    """
    return f"{settings.s3_public_url.rstrip('/')}/{quote(key)}"


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
