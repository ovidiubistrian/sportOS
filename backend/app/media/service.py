"""Media validation and intake.

Everything a club uploads passes through here, and the order of the checks is
the point: **decide what the bytes are before deciding what to do with them.**

A browser's `Content-Type` and a filename's extension are both supplied by the
uploader. Trusting either is how a `.svg` containing a script, or a polyglot
file that is a valid GIF and a valid HTML page, ends up served from the club's
own origin. So the declared type is used for nothing: the format is read from
the bytes by an image decoder, and the extension we store is derived from what
the decoder actually found.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import structlog
from PIL import Image, UnidentifiedImageError

from app.core.errors import ValidationFailed

log = structlog.get_logger(__name__)

# Raster only, and deliberately no SVG. An SVG is a document: it can carry
# script, external references and entity expansions, and sanitising it safely is
# a losing arms race. A club that wants a crisp crest uploads a large PNG.
ALLOWED_FORMATS: dict[str, tuple[str, str]] = {
    # Pillow format -> (extension, content type)
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}

MAX_BYTES = 8 * 1024 * 1024
# A guard against decompression bombs: a 10KB PNG can declare 40,000 by 40,000
# pixels and cost gigabytes to decode. Checked from the header, before the
# pixels are ever read.
MAX_PIXELS = 40_000_000
MAX_DIMENSION = 8_000
MIN_DIMENSION = 16


@dataclass(frozen=True, slots=True)
class InspectedImage:
    format: str
    extension: str
    content_type: str
    width: int
    height: int
    size_bytes: int


def inspect(data: bytes) -> InspectedImage:
    """Establish what the bytes actually are, or refuse them."""
    if not data:
        raise ValidationFailed("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ValidationFailed(
            f"That image is larger than {MAX_BYTES // (1024 * 1024)} MB.",
            size_bytes=len(data),
            maximum=MAX_BYTES,
        )

    try:
        # `open` reads the header only, so the size check below happens before
        # anything decodes the image data.
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format or ""
            width, height = image.size

            if fmt not in ALLOWED_FORMATS:
                raise ValidationFailed(
                    "That file type is not supported. Use a PNG, JPEG or WebP image.",
                    detected=fmt or "unknown",
                )
            if width * height > MAX_PIXELS or max(width, height) > MAX_DIMENSION:
                raise ValidationFailed(
                    "That image's dimensions are too large.",
                    width=width,
                    height=height,
                )
            if min(width, height) < MIN_DIMENSION:
                raise ValidationFailed(
                    "That image is too small to use.", width=width, height=height
                )

            # Force a full decode. A file whose header parses but whose data is
            # truncated or malformed fails here rather than in whatever renders
            # it later.
            image.verify()
    except UnidentifiedImageError as exc:
        raise ValidationFailed(
            "That file is not an image we can read. Use a PNG, JPEG or WebP."
        ) from exc
    except ValidationFailed:
        raise
    except Exception as exc:
        log.info("media_decode_failed", error=str(exc))
        raise ValidationFailed("That image could not be read. It may be damaged.") from exc

    extension, content_type = ALLOWED_FORMATS[fmt]
    return InspectedImage(
        format=fmt,
        extension=extension,
        content_type=content_type,
        width=width,
        height=height,
        size_bytes=len(data),
    )
