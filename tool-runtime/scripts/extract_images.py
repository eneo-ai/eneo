"""Cuts the pictures out of one PDF, Word or PowerPoint file.

Run by the tool runtime's sandbox child as ``python3 -I -B extract_images.py <job.json>``.
The job names the downloaded file, its kind, the window of pictures wanted and an output
directory, all inside one directory the runtime made for this call. Each picture of the
window is written there as a PNG or JPEG, the formats a document embeds. Prints
``{"total": n, "images": [...]}`` on success: how many pictures the file has, and for each
one written its file name, media type, pixel size and (for a PDF) page.

A PDF picture is found by where a page places an image and is taken from a rendering of
that region, so every PDF image codec comes out as a plain bitmap with masks, rotation and
clipping applied. Charts and diagrams drawn as vector graphics are no image on the page and
are not found. An Office picture is an embedded raster media entry.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

# A picture smaller than this (in source pixels) is a bullet, an icon or a rule.
MIN_SOURCE_PIXELS = 100
# A picture shown smaller than this on a PDF page (in points) is decoration.
MIN_DISPLAY_POINTS = 36.0
# Print resolution: a page is never rendered sharper, however dense the picture.
MAX_RENDER_DPI = 300
# Longest edge a page is rendered at: bounds the render's memory on poster-sized pages.
MAX_PAGE_EDGE = 4096
# Longest edge of a picture as delivered.
MAX_PICTURE_EDGE = 2048
# A picture is kept lossless up to this size; larger ones (photos) are stored as JPEG.
MAX_PNG_BYTES = 1024 * 1024
JPEG_QUALITY = 85
# An image's data is hashed to recognise a repeat; one larger than this is not hashed.
MAX_HASHED_BYTES = 32 * 1024 * 1024
# Media entries of one Office file considered, and the size one may inflate to.
MAX_MEDIA_ENTRIES = 500
MAX_MEDIA_BYTES = 30 * 1024 * 1024
MEDIA_DIRECTORIES = {"docx": "word/media/", "pptx": "ppt/media/"}


def encode(image, directory: Path, index: int, page: int | None = None) -> dict:
    """Writes one picture as PNG, or as JPEG when it is a large photo."""
    from PIL import Image

    if max(image.size) > MAX_PICTURE_EDGE:
        image.thumbnail((MAX_PICTURE_EDGE, MAX_PICTURE_EDGE), Image.Resampling.LANCZOS)
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    buffer = io.BytesIO()
    extension, media_type = "png", "image/png"
    if has_alpha:
        image.convert("RGBA").save(buffer, format="PNG", optimize=True)
    else:
        image = image.convert("RGB")
        image.save(buffer, format="PNG", optimize=True)
        if buffer.tell() > MAX_PNG_BYTES:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
            extension, media_type = "jpg", "image/jpeg"
    name = f"picture-{index}.{extension}"
    (directory / name).write_bytes(buffer.getvalue())
    return {
        "file": name,
        "mime_type": media_type,
        "width": image.width,
        "height": image.height,
        **({"page": page} if page is not None else {}),
    }


def page_corners(image) -> list[tuple[float, float]]:
    """The corners of an image object in page coordinates.

    An object inside a Form XObject reports its position in the form's own space; each
    enclosing form's matrix carries it out to the page.
    """
    corners = list(image.get_quad_points())
    container = image.container
    while container is not None:
        matrix = container.get_matrix()
        corners = [matrix.on_point(x, y) for x, y in corners]
        container = container.container
    return corners


def pdf_pictures(document, max_pages: int, only_page: int | None) -> list[dict]:
    """Every picture of the document in page order: its page and where it is placed."""
    import pypdfium2.raw as pdfium_c

    pictures: list[dict] = []
    seen: set[bytes] = set()
    for index in range(min(len(document), max_pages)):
        number = index + 1
        if only_page is not None and number > only_page:
            break
        page = document[index]
        try:
            for image in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
                try:
                    source_width, source_height = image.get_px_size()
                    corners = page_corners(image)
                except Exception:
                    continue
                if min(source_width, source_height) < MIN_SOURCE_PIXELS:
                    continue
                xs = [x for x, _ in corners]
                ys = [y for _, y in corners]
                if (
                    max(xs) - min(xs) < MIN_DISPLAY_POINTS
                    or max(ys) - min(ys) < MIN_DISPLAY_POINTS
                ):
                    continue
                # A picture the document repeats (a logo on every page) comes out once.
                # Earlier pages are read even when one page is asked for, so a repeat is
                # known when that page shows it again.
                try:
                    data = bytes(image.get_data(decode_simple=False))
                except Exception:
                    data = b""
                if data and len(data) <= MAX_HASHED_BYTES:
                    digest = hashlib.sha256(data).digest()
                    if digest in seen:
                        continue
                    seen.add(digest)
                if only_page is None or number == only_page:
                    pictures.append(
                        {
                            "page": number,
                            "corners": corners,
                            "source_width": source_width,
                            "width_points": max(xs) - min(xs),
                        }
                    )
        finally:
            page.close()
    return pictures


def render_pdf_picture(document, picture: dict):
    """The region of the rendered page that shows one picture."""
    import pypdfium2.raw as pdfium_c

    page = document[picture["page"] - 1]
    try:
        # Sharp enough to keep the picture's own pixels, within print resolution and a
        # bounded page render.
        native = picture["source_width"] / (picture["width_points"] / 72)
        page_inches = max(page.get_width(), page.get_height()) / 72
        dpi = max(1.0, min(native, MAX_RENDER_DPI, MAX_PAGE_EDGE / page_inches))
        rendered = page.render(scale=dpi / 72).to_pil()
        # The page's own rotation and crop box are part of the mapping to the rendering.
        xs: list[int] = []
        ys: list[int] = []
        for x, y in picture["corners"]:
            device_x, device_y = ctypes.c_int(), ctypes.c_int()
            pdfium_c.FPDF_PageToDevice(
                page, 0, 0, rendered.width, rendered.height, 0, x, y, device_x, device_y
            )
            xs.append(device_x.value)
            ys.append(device_y.value)
        box = (
            max(min(xs), 0),
            max(min(ys), 0),
            min(max(xs), rendered.width),
            min(max(ys), rendered.height),
        )
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return None
        return rendered.crop(box)
    finally:
        page.close()


def extract_pdf(job: dict, source: Path, output: Path) -> dict:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(source)
    try:
        pictures = pdf_pictures(document, job["max_pages"], job.get("page"))
        images = []
        window = pictures[job["offset"] : job["offset"] + job["limit"]]
        for index, picture in enumerate(window):
            cropped = render_pdf_picture(document, picture)
            if cropped is not None:
                images.append(encode(cropped, output, index, picture["page"]))
        return {"total": len(pictures), "images": images}
    finally:
        document.close()


def natural_key(name: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def extract_office(job: dict, source: Path, output: Path) -> dict:
    from PIL import Image

    directory = MEDIA_DIRECTORIES[job["kind"]]
    offset, limit = job["offset"], job["limit"]
    images = []
    total = 0
    with zipfile.ZipFile(source) as archive:
        entries = sorted(
            (info for info in archive.infolist() if info.filename.startswith(directory)),
            key=lambda info: natural_key(info.filename),
        )
        for entry in entries[:MAX_MEDIA_ENTRIES]:
            if entry.file_size > MAX_MEDIA_BYTES:
                continue
            try:
                with Image.open(io.BytesIO(archive.read(entry.filename))) as image:
                    # The header gives the size; only a picture in the window is decoded.
                    if min(image.size) < MIN_SOURCE_PIXELS:
                        continue
                    if offset <= total < offset + limit:
                        image.load()
                        images.append(encode(image, output, total - offset))
            except Exception:
                # Vector media (EMF, WMF) and anything else Pillow cannot read.
                continue
            total += 1
    return {"total": total, "images": images}


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base = Path(job["base_dir"]).resolve()
    source = Path(job["input_path"]).resolve()
    output = Path(job["output_dir"]).resolve()
    for path in (source, output):
        if base not in path.parents:
            raise SystemExit(f"{path} is outside the job directory")
    extract = extract_pdf if job["kind"] == "pdf" else extract_office
    print(json.dumps(extract(job, source, output)))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
