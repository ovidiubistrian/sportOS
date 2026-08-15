"""Media routes.

Upload, list and delete images for a club. Bytes go through the API rather than
straight to storage on a presigned URL: at club scale — a crest, a hero image,
a dozen partner logos — the throughput saving is irrelevant, and having the
bytes in hand is what lets us decide the file really is an image before it is
ever addressable. A presigned PUT would have to trust the uploader and check
afterwards, which leaves a window where an unvalidated object exists at a URL.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Db, Requires
from app.audit.service import AuditService
from app.core.context import RequestContext
from app.core.errors import NotFound, ValidationFailed
from app.core.ids import new_id
from app.media import storage
from app.media.models import MEDIA_PURPOSES, MediaAsset
from app.media.service import MAX_BYTES, inspect

router = APIRouter(prefix="/media", tags=["media"])

READ = "clubs.club.read"
WRITE = "clubs.club.update"


class MediaOut(BaseModel):
    id: UUID
    club_id: UUID
    purpose: str
    url: str
    width: int
    height: int
    size_bytes: int
    content_type: str
    alt_text: str | None
    original_filename: str | None

    @classmethod
    def of(cls, asset: MediaAsset) -> MediaOut:
        return cls(
            id=asset.id,
            club_id=asset.club_id,
            purpose=asset.purpose,
            url=storage.public_url(asset.storage_key),
            width=asset.width,
            height=asset.height,
            size_bytes=asset.size_bytes,
            content_type=asset.content_type,
            alt_text=asset.alt_text,
            original_filename=asset.original_filename,
        )


class AltTextUpdate(BaseModel):
    alt_text: str = Field(min_length=1, max_length=300)


@router.get("", response_model=list[MediaOut], summary="Images for a club")
async def list_media(
    club_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(READ))],
    purpose: str | None = None,
) -> list[MediaOut]:
    stmt = select(MediaAsset).where(
        MediaAsset.tenant_id == ctx.tenant, MediaAsset.club_id == club_id
    )
    if purpose:
        stmt = stmt.where(MediaAsset.purpose == purpose)
    assets = await db.scalars(stmt.order_by(MediaAsset.created_at.desc()).limit(200))
    return [MediaOut.of(asset) for asset in assets]


@router.post(
    "",
    response_model=MediaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image",
    responses={
        413: {"description": "The file is larger than the limit"},
        422: {"description": "Not a supported image"},
    },
)
async def upload(
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
    club_id: Annotated[UUID, Form()],
    purpose: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    alt_text: Annotated[str | None, Form()] = None,
) -> MediaOut:
    if purpose not in MEDIA_PURPOSES:
        raise ValidationFailed(f"Unknown purpose {purpose!r}.", known=sorted(MEDIA_PURPOSES))

    # Bounded read. Without the cap, a client can stream gigabytes into memory
    # before any size check has a chance to run.
    data = await file.read(MAX_BYTES + 1)
    image = inspect(data)

    asset_id = new_id()
    key = storage.object_key(
        visibility=storage.Visibility.PUBLIC,
        tenant_id=str(ctx.tenant),
        club_id=str(club_id),
        asset_id=str(asset_id),
        extension=image.extension,
    )

    # Storage first: a row pointing at an object that does not exist renders as
    # a broken image on the club's website. An object with no row is invisible
    # and is reclaimed by the orphan sweep.
    await storage.put(key, data, content_type=image.content_type)

    asset = MediaAsset(
        id=asset_id,
        tenant_id=ctx.tenant,
        club_id=club_id,
        purpose=purpose,
        visibility=storage.Visibility.PUBLIC.value,
        storage_key=key,
        content_type=image.content_type,
        size_bytes=image.size_bytes,
        width=image.width,
        height=image.height,
        # Kept as a label so an editor recognises their own upload; never used
        # to build a URL.
        original_filename=(file.filename or "")[:255] or None,
        alt_text=(alt_text or "").strip()[:300] or None,
        uploaded_by=ctx.actor_id,
    )
    db.add(asset)
    await db.flush()

    AuditService(db).record(
        ctx,
        action="media.asset.upload",
        object_type="media_asset",
        object_id=asset.id,
        club_id=club_id,
        after={"purpose": purpose, "size_bytes": image.size_bytes},
    )
    return MediaOut.of(asset)


@router.patch("/{asset_id}", response_model=MediaOut, summary="Set alt text")
async def set_alt_text(
    asset_id: UUID,
    payload: AltTextUpdate,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> MediaOut:
    asset = await db.scalar(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.tenant_id == ctx.tenant)
    )
    if asset is None:
        raise NotFound(object_type="media_asset", object_id=str(asset_id))
    asset.alt_text = payload.alt_text.strip()
    await db.flush()
    return MediaOut.of(asset)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an image")
async def remove(
    asset_id: UUID,
    db: Db,
    ctx: Annotated[RequestContext, Depends(Requires(WRITE))],
) -> None:
    asset = await db.scalar(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.tenant_id == ctx.tenant)
    )
    if asset is None:
        raise NotFound(object_type="media_asset", object_id=str(asset_id))

    AuditService(db).record(
        ctx,
        action="media.asset.delete",
        object_type="media_asset",
        object_id=asset.id,
        club_id=asset.club_id,
        before={"purpose": asset.purpose},
    )
    key = asset.storage_key
    await db.delete(asset)
    await db.flush()
    # The row goes first. If the object delete fails, the club sees the image
    # gone from the admin and the orphan sweep reclaims the bytes — the other
    # order would leave a live row pointing at nothing.
    await storage.delete(key)
