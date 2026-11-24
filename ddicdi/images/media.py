"""Decoding an uploaded image: format, size, checksum, and the JPEG preview and thumbnail kept.

Only JPEG, PNG, WebP and TIFF are accepted, decided by the decoded format, not the file
name. The pixel count is checked before the image is decoded, so a small file that
would expand into a huge bitmap (a decompression bomb) is refused. Animated or
multi-page files are described by their first frame.
"""

from __future__ import annotations

import hashlib
import io
import re
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings

# Pillow format name -> media type written as the distribution's encodingFormat.
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "TIFF": "image/tiff"}
# Phone and camera photos are often MPO: a JPEG carrying extra pictures (a depth map, a
# preview). Pillow names the format MPO even when only JPEG is asked for; the file is
# still a JPEG, and its first picture is the photo.
FORMAT_ALIASES = {"MPO": "JPEG"}
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")


class ImageRejected(ValueError):
    """Not an accepted image, or over a limit."""


@dataclass
class Processed:
    mime: str
    width: int
    height: int
    size: int
    md5: str
    preview: bytes  # JPEG, long side at most settings.image_preview_side
    thumb: bytes  # JPEG, long side at most settings.image_thumb_side
    taken: str = ""  # YYYY-MM-DD the photo was taken (EXIF), "" when not recorded


_EXIF_DATE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})")


def iso_day(value: str) -> str:
    """``value`` when it is a real calendar day as YYYY-MM-DD, otherwise ""."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    if not m:
        return ""
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return ""


def exif_taken(im: Image.Image) -> str:
    """The day a photo was taken: EXIF DateTimeOriginal, else DateTimeDigitized, else
    DateTime. Cameras write "YYYY:MM:DD HH:MM:SS"; an unset one is "0000:00:00 ..."."""
    try:
        exif = im.getexif()
        sub = exif.get_ifd(0x8769)  # the Exif IFD
        candidates = (sub.get(36867), sub.get(36868), exif.get(306))
    except Exception:  # a broken EXIF block must not refuse the picture
        return ""
    for raw in candidates:
        m = _EXIF_DATE.match(str(raw or "").strip())
        if m and (day := iso_day(f"{m[1]}-{m[2]}-{m[3]}")):
            return day
    return ""


def _jpeg(im: Image.Image, side: int, quality: int) -> bytes:
    copy = im.copy()
    copy.thumbnail((side, side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _rgb(im: Image.Image) -> Image.Image:
    """The image on a white background: JPEG has no transparency."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im.convert("RGB")


def process(content: bytes, filename: str) -> Processed:
    if Path(filename).suffix.lower() not in EXTENSIONS:
        raise ImageRejected(f"{filename!r}: only JPEG, PNG, WebP and TIFF images are accepted")
    limit = settings.max_image_bytes
    if limit > 0 and len(content) > limit:
        raise ImageRejected(f"{filename!r} is {len(content)} bytes; the limit is {limit}")
    # Pillow's own bomb check follows the setting (it warns above the limit, fails at twice it).
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels if settings.max_image_pixels > 0 else None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(content), formats=list(FORMATS))
            pixels = im.width * im.height
            if settings.max_image_pixels > 0 and pixels > settings.max_image_pixels:
                raise ImageRejected(
                    f"{filename!r} is {im.width}x{im.height} pixels; the limit is {settings.max_image_pixels:,} pixels"
                )
            fmt = FORMAT_ALIASES.get(im.format, im.format)
            if fmt not in FORMATS:
                raise ImageRejected(f"{filename!r} is {im.format}; only JPEG, PNG, WebP and TIFF images are accepted")
            mime = FORMATS[fmt]
            taken = exif_taken(im)
            im.seek(0)
            im.load()
            im = ImageOps.exif_transpose(im)  # the preview the right way up; EXIF is not kept
            rgb = _rgb(im)
    except ImageRejected:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageRejected(f"{filename!r} is not a readable JPEG, PNG, WebP or TIFF image ({exc})") from exc
    except (OSError, ValueError, SyntaxError) as exc:  # truncated or corrupt files
        raise ImageRejected(f"{filename!r} could not be decoded ({exc})") from exc
    return Processed(
        mime=mime,
        width=rgb.width,
        height=rgb.height,
        size=len(content),
        md5=hashlib.md5(content).hexdigest(),
        preview=_jpeg(rgb, settings.image_preview_side, 85),
        thumb=_jpeg(rgb, settings.image_thumb_side, 80),
        taken=taken,
    )
