from pathlib import Path

from intric.files.text import MimeTypesBase
from intric.main.exceptions import FileNotSupportedException


class ImageMimeTypes(MimeTypesBase):
    PNG = "image/png"
    JPEG = "image/jpeg"


class ImageExtractor:
    @staticmethod
    def extract_from_image(filepath: Path) -> bytes:
        with open(filepath, "rb") as image_file:
            return image_file.read()

    def extract(
        self, filepath: Path, mimetype: str, filename: str | None = None
    ) -> bytes:
        if ImageMimeTypes.has_value(mimetype):
            return self.extract_from_image(filepath)

        display_name = filename or filepath.name
        raise FileNotSupportedException(f"Image format not supported for '{display_name}'")
