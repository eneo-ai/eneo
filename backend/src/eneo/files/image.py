from pathlib import Path

from eneo.files.text import MimeTypesBase
from eneo.main.exceptions import FileNotSupportedException


class ImageMimeTypes(MimeTypesBase):
    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"
    AVIF = "image/avif"
    HEIC = "image/heic"
    HEIF = "image/heif"


class ImageExtractor:
    @staticmethod
    def extract_from_image(filepath: Path) -> bytes:
        with open(filepath, "rb") as image_file:
            return image_file.read()

    def extract(self, filepath: Path, mimetype: str) -> bytes:
        if ImageMimeTypes.has_value(mimetype):
            return self.extract_from_image(filepath)

        raise FileNotSupportedException("Image format not supported")
