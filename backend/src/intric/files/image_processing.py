"""Image normalization for vision input and image extraction from PDFs.

Images sent to vision models are base64-encoded into the request payload, so
oversized uploads waste tokens and bandwidth. Everything that ends up as a
vision image (direct uploads and PDF-derived images alike) is routed through
downscale_image() so the stored blob matches what is sent and counted.
"""

import io
import logging
from dataclasses import dataclass
from pathlib import Path

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

# Embedded PDF images smaller than this (in source pixels) are skipped —
# they are typically logos, icons or decorations.
MIN_PDF_IMAGE_DIMENSION = 200


@dataclass
class ProcessedImage:
    blob: bytes
    mimetype: str


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


def extract_images_from_pdf(
    filepath: Path,
    *,
    max_images: int,
    min_dimension: int = MIN_PDF_IMAGE_DIMENSION,
) -> list[ProcessedImage]:
    """Extract embedded images from a PDF by rendering their page regions.

    Rendering the bounding box (rather than decoding the raw image stream)
    sidesteps PDF codec variety — CCITT/JBIG2/JPX streams all come out as
    plain bitmaps. Scanned pages are covered too: the scan is one embedded
    image spanning the page, so its region is the whole page.

    Never raises: extraction is best-effort enrichment of a text upload.
    """
    import pdfplumber

    extracted: list[ProcessedImage] = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                if len(extracted) >= max_images:
                    break
                for image_meta in page.images:
                    if len(extracted) >= max_images:
                        break

                    source_width, source_height = image_meta.get(
                        "srcsize", (None, None)
                    )
                    if (
                        not source_width
                        or not source_height
                        or source_width < min_dimension
                        or source_height < min_dimension
                    ):
                        continue

                    # Clamp the image bbox to the page bbox — embedded images
                    # can bleed outside it, which crop() rejects.
                    x0 = max(image_meta["x0"], page.bbox[0])
                    top = max(image_meta["top"], page.bbox[1])
                    x1 = min(image_meta["x1"], page.bbox[2])
                    bottom = min(image_meta["bottom"], page.bbox[3])
                    if x1 - x0 <= 1 or bottom - top <= 1:
                        continue

                    try:
                        # Render at a resolution that roughly reproduces the
                        # source pixel density, capped by the vision limit.
                        bbox_width_inches = (x1 - x0) / 72
                        resolution = min(
                            int(source_width / bbox_width_inches),
                            int(MAX_IMAGE_DIMENSION / bbox_width_inches),
                        )
                        resolution = max(resolution, 72)
                        cropped = page.crop((x0, top, x1, bottom))
                        rendered = cropped.to_image(resolution=resolution)

                        buffer = io.BytesIO()
                        rendered.original.convert("RGB").save(
                            buffer, format="JPEG", quality=JPEG_QUALITY
                        )
                        extracted.append(
                            downscale_image(buffer.getvalue(), "image/jpeg")
                        )
                    except Exception as e:
                        logger.warning(
                            f"Skipping unrenderable image on page {page.page_number} "
                            f"of '{filepath.name}': {e}"
                        )
    except Exception as e:
        logger.warning(f"PDF image extraction failed for '{filepath.name}': {e}")

    return extracted
