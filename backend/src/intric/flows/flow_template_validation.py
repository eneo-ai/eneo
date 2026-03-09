"""Compatibility re-export for DOCX template validation helpers.

Keep this module path stable for existing imports while the implementation
resides in the files domain to avoid import cycles during backend startup.
"""

from intric.files.docx_template_validation import (
    normalize_template_extraction_error,
    validate_docx_template_archive,
    validate_template_extension,
)

__all__ = [
    "normalize_template_extraction_error",
    "validate_docx_template_archive",
    "validate_template_extension",
]
