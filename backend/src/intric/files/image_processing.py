"""Image normalization for vision input and image extraction from documents.

Images sent to vision models are base64-encoded into the request payload, so
oversized uploads waste tokens and bandwidth. Everything that ends up as a
vision image (direct uploads and document-derived images alike) is routed
through downscale_image() so the stored blob matches what is sent and counted.
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

try:
    import pillow_heif  # pyright: ignore[reportMissingTypeStubs]  # no stubs published

    pillow_heif.register_heif_opener()  # pyright: ignore[reportUnknownMemberType]
except ImportError:  # pragma: no cover — optional decoder
    pass

logger = logging.getLogger(__name__)

# Formats vision providers accept as-is; anything else (HEIC, AVIF, TIFF…)
# must be converted even if conversion does not shrink the blob.
_PROVIDER_SAFE_FORMATS = {"PNG", "JPEG", "WEBP"}

# Max longest edge for vision input. Providers downscale anyway (OpenAI caps
# at 2048px before tiling), so larger images only cost transfer size.
MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85

# Embedded images smaller than this (in source pixels) are skipped —
# they are typically logos, icons or decorations.
MIN_EMBEDDED_IMAGE_DIMENSION = 200

# Page-render resolution cap: small pages need not be rendered sharper than
# print resolution even when they fit inside MAX_IMAGE_DIMENSION.
_PAGE_RENDER_MAX_DPI = 300

# Vector-graphics heuristics (see _page_has_visual_content). Tables and text
# layout draw axis-aligned stroked lines/rects; charts and diagrams show up
# as curves, diagonal lines, or clusters of filled rects (bars, heat maps).
_MIN_CURVES_FOR_GRAPHICS = 10
_MIN_DIAGONAL_LINES_FOR_GRAPHICS = 2
_MIN_FILLED_RECTS_FOR_GRAPHICS = 5

# OOXML archives keep embedded media under a fixed directory per format.
_OFFICE_MEDIA_DIRS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "word/media/"
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "ppt/media/"
    ),
}

# Decompression-bomb guard: a zip entry may inflate far beyond the upload
# size limit, and no legitimate embedded image needs this much.
_MAX_EMBEDDED_MEDIA_BYTES = 30 * 1024 * 1024


@dataclass
class ProcessedImage:
    blob: bytes
    mimetype: str
    page_number: int | None = None


def downscale_image(blob: bytes, mimetype: str | None) -> ProcessedImage:
    """Resize/recompress an image for vision input.

    Returns the original blob untouched when processing does not make it
    smaller (already small, or an efficiently compressed format), or when the
    blob cannot be decoded — sending the original is better than failing.
    """
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image.load()
            needs_conversion = (image.format or "") not in _PROVIDER_SAFE_FORMATS
            needs_resize = max(image.size) > MAX_IMAGE_DIMENSION
            if needs_resize:
                image.thumbnail(
                    (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                    Image.Resampling.LANCZOS,
                )

            has_alpha = image.mode in ("RGBA", "LA", "PA") or (
                image.mode == "P" and "transparency" in image.info
            )
            buffer = io.BytesIO()
            if has_alpha:
                image.save(buffer, format="PNG", optimize=True)
                new_mimetype = "image/png"
            else:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
                new_mimetype = "image/jpeg"

            processed = buffer.getvalue()
    except Exception as e:
        logger.warning(f"Could not process image for downscaling: {e}")
        return ProcessedImage(blob=blob, mimetype=mimetype or "image/png")

    if not needs_resize and not needs_conversion and len(processed) >= len(blob):
        return ProcessedImage(blob=blob, mimetype=mimetype or "image/png")
    return ProcessedImage(blob=processed, mimetype=new_mimetype)


def _center_in_any_bbox(
    obj: dict[str, Any], bboxes: list[tuple[float, float, float, float]]
) -> bool:
    center_x = (float(obj["x0"]) + float(obj["x1"])) / 2
    center_y = (float(obj["top"]) + float(obj["bottom"])) / 2
    return any(
        x0 <= center_x <= x1 and top <= center_y <= bottom
        for (x0, top, x1, bottom) in bboxes
    )


def _page_has_visual_content(page: Any, min_dimension: int) -> bool:
    # pdfplumber ships no type stubs — treat the page as Any and pin the
    # types we rely on at the boundaries.
    for image_meta in page.images:
        source_width, source_height = image_meta.get("srcsize", (None, None))
        if (
            source_width
            and source_height
            and source_width >= min_dimension
            and source_height >= min_dimension
        ):
            return True

    if len(page.curves) >= _MIN_CURVES_FOR_GRAPHICS:
        return True

    diagonal_lines: list[dict[str, Any]] = [
        line
        for line in page.lines
        if abs(line["x1"] - line["x0"]) > 1 and abs(line["bottom"] - line["top"]) > 1
    ]
    if len(diagonal_lines) >= _MIN_DIAGONAL_LINES_FOR_GRAPHICS:
        return True

    filled_rects: list[dict[str, Any]] = [
        rect for rect in page.rects if rect.get("fill")
    ]
    if len(filled_rects) >= _MIN_FILLED_RECTS_FOR_GRAPHICS:
        # Shaded table cells are filled rects too — only fills outside
        # detected tables count as graphics (bars, heat maps, infographics).
        table_bboxes: list[tuple[float, float, float, float]] = [
            tuple(table.bbox) for table in page.find_tables()
        ]
        outside = [
            rect for rect in filled_rects if not _center_in_any_bbox(rect, table_bboxes)
        ]
        if len(outside) >= _MIN_FILLED_RECTS_FOR_GRAPHICS:
            return True

    return False


def _render_page(page: Any) -> ProcessedImage | None:
    width_inches = float(page.width) / 72
    height_inches = float(page.height) / 72
    if width_inches <= 0 or height_inches <= 0:
        return None

    # Cap the longest rendered edge — bounds render memory even for
    # degenerate page sizes (a 200-inch page renders tiny, not huge).
    resolution = int(MAX_IMAGE_DIMENSION / max(width_inches, height_inches))
    resolution = max(min(resolution, _PAGE_RENDER_MAX_DPI), 1)

    rendered = page.to_image(resolution=resolution)
    buffer = io.BytesIO()
    rendered.original.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    processed = downscale_image(buffer.getvalue(), "image/jpeg")
    return ProcessedImage(
        blob=processed.blob,
        mimetype=processed.mimetype,
        page_number=int(page.page_number),
    )


def extract_images_from_pdf(
    filepath: Path,
    *,
    max_images: int,
    min_dimension: int = MIN_EMBEDDED_IMAGE_DIMENSION,
) -> list[ProcessedImage]:
    """Render the PDF pages that carry visual content, for vision input.

    Whole-page rendering (rather than decoding embedded image streams)
    sidesteps PDF codec variety — CCITT/JBIG2/JPX all come out as plain
    bitmaps — and also captures vector graphics: charts, diagrams and
    drawings that exist only as draw operations with no embedded raster.
    Scanned pages are one embedded image spanning the page.

    Never raises: extraction is best-effort enrichment of a text upload.
    """
    import pdfplumber

    extracted: list[ProcessedImage] = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                if len(extracted) >= max_images:
                    logger.info(
                        f"Page-image cap ({max_images}) reached for "
                        f"'{filepath.name}'; later pages were not scanned"
                    )
                    break
                try:
                    if not _page_has_visual_content(page, min_dimension):
                        continue
                    rendered = _render_page(page)
                    if rendered is not None:
                        extracted.append(rendered)
                except Exception as e:
                    logger.warning(
                        f"Skipping unrenderable page {page.page_number} "
                        f"of '{filepath.name}': {e}"
                    )
    except Exception as e:
        logger.warning(f"PDF image extraction failed for '{filepath.name}': {e}")

    return extracted


def _natural_sort_key(name: str) -> tuple[str | int, ...]:
    return tuple(
        int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)
    )


def extract_images_from_office(
    filepath: Path,
    *,
    mimetype: str,
    max_images: int,
    min_dimension: int = MIN_EMBEDDED_IMAGE_DIMENSION,
) -> list[ProcessedImage]:
    """Extract embedded raster images from OOXML archives (DOCX/PPTX).

    Vector media (EMF/WMF) and anything else Pillow cannot decode is
    skipped. Never raises: extraction is best-effort enrichment.
    """
    media_dir = _OFFICE_MEDIA_DIRS.get(mimetype)
    if media_dir is None:
        return []

    extracted: list[ProcessedImage] = []
    try:
        with zipfile.ZipFile(filepath) as archive:
            entries = sorted(
                (
                    info
                    for info in archive.infolist()
                    if info.filename.startswith(media_dir)
                ),
                key=lambda info: _natural_sort_key(info.filename),
            )
            for entry in entries:
                if len(extracted) >= max_images:
                    logger.info(
                        f"Embedded-image cap ({max_images}) reached for "
                        f"'{filepath.name}'; later media entries were skipped"
                    )
                    break
                if entry.file_size > _MAX_EMBEDDED_MEDIA_BYTES:
                    logger.warning(
                        f"Skipping oversized media entry '{entry.filename}' "
                        f"({entry.file_size} bytes) in '{filepath.name}'"
                    )
                    continue

                blob = archive.read(entry.filename)
                try:
                    with Image.open(io.BytesIO(blob)) as image:
                        image.load()
                        width, height = image.size
                        media_mimetype = Image.MIME.get(image.format or "", "image/png")
                except Exception:
                    continue
                if width < min_dimension or height < min_dimension:
                    continue

                extracted.append(downscale_image(blob, media_mimetype))
    except Exception as e:
        logger.warning(f"Office image extraction failed for '{filepath.name}': {e}")

    return extracted
