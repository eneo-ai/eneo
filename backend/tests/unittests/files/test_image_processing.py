import io
from pathlib import Path

from PIL import Image

from intric.files.image_processing import (
    MAX_IMAGE_DIMENSION,
    downscale_image,
    extract_images_from_pdf,
)


def _image_bytes(width: int, height: int, mode: str = "RGB", fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new(
        mode, (width, height), color=(120, 30, 30) if mode == "RGB" else None
    ).save(buffer, format=fmt)
    return buffer.getvalue()


def test_downscale_resizes_oversized_image():
    blob = _image_bytes(4096, 2048)

    processed = downscale_image(blob, "image/png")

    with Image.open(io.BytesIO(processed.blob)) as result:
        assert max(result.size) <= MAX_IMAGE_DIMENSION
    assert processed.mimetype == "image/jpeg"


def test_downscale_preserves_alpha_as_png():
    blob = _image_bytes(3000, 3000, mode="RGBA")

    processed = downscale_image(blob, "image/png")

    assert processed.mimetype == "image/png"
    with Image.open(io.BytesIO(processed.blob)) as result:
        assert result.mode == "RGBA"
        assert max(result.size) <= MAX_IMAGE_DIMENSION


def test_downscale_keeps_small_efficient_image_untouched():
    blob = _image_bytes(100, 100, fmt="PNG")

    processed = downscale_image(blob, "image/png")

    # Solid-color 100px PNG is already tiny; recompression cannot beat it
    assert processed.blob == blob
    assert processed.mimetype == "image/png"


def test_downscale_converts_heic_to_jpeg():
    # HEIC must always be converted — providers reject image/heic payloads —
    # even when the converted blob is larger than the original.
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), color=(50, 120, 60)).save(buffer, format="HEIF")

    processed = downscale_image(buffer.getvalue(), "image/heic")

    assert processed.mimetype == "image/jpeg"
    with Image.open(io.BytesIO(processed.blob)) as result:
        assert result.format == "JPEG"


def test_downscale_returns_original_on_undecodable_blob():
    processed = downscale_image(b"not an image", "image/png")

    assert processed.blob == b"not an image"
    assert processed.mimetype == "image/png"


def _pdf_with_image(tmp_path: Path, width: int = 800, height: int = 600) -> Path:
    # Pillow writes a PDF whose page embeds the image — same structure as a
    # scanned document (one image spanning the page).
    pdf_path = tmp_path / "with_image.pdf"
    Image.new("RGB", (width, height), color=(10, 90, 160)).save(pdf_path)
    return pdf_path


def test_extract_images_from_pdf(tmp_path: Path):
    pdf_path = _pdf_with_image(tmp_path)

    images = extract_images_from_pdf(pdf_path, max_images=8)

    assert len(images) == 1
    assert images[0].mimetype == "image/jpeg"
    with Image.open(io.BytesIO(images[0].blob)) as result:
        assert result.size[0] > 100


def test_extract_skips_small_images(tmp_path: Path):
    pdf_path = _pdf_with_image(tmp_path, width=100, height=100)

    images = extract_images_from_pdf(pdf_path, max_images=8)

    assert images == []


def test_extract_respects_max_images_cap(tmp_path: Path):
    pdf_path = tmp_path / "many_pages.pdf"
    pages = [Image.new("RGB", (800, 600), color=(i * 20, 50, 50)) for i in range(5)]
    pages[0].save(pdf_path, save_all=True, append_images=pages[1:])

    images = extract_images_from_pdf(pdf_path, max_images=2)

    assert len(images) == 2


def test_extract_handles_image_free_pdf(tmp_path: Path):
    import pdfplumber  # noqa: F401  — ensure dependency present for fixture parity

    pdf_path = tmp_path / "no_image.pdf"
    # Minimal valid single-page PDF without images
    pdf_path.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000052 00000 n \n0000000101 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n164\n%%EOF"
    )

    assert extract_images_from_pdf(pdf_path, max_images=8) == []


def test_extract_never_raises_on_garbage(tmp_path: Path):
    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"not a pdf at all")

    assert extract_images_from_pdf(garbage, max_images=8) == []
