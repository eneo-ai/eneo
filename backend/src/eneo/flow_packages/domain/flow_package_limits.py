"""Flow compatibility names for the shared resource-package and DOCX limits."""

from eneo.files.docx_template_validation import MAX_TEMPLATE_UNCOMPRESSED_BYTES
from eneo.resource_packages.limits import MAX_RESOURCE_PACKAGE_BYTES

MAX_FLOW_PACKAGE_BYTES = MAX_RESOURCE_PACKAGE_BYTES

# Total bytes all distinct Word templates of one package import may unpack to.
# One template may unpack to MAX_TEMPLATE_UNCOMPRESSED_BYTES; a package carries up
# to 256 template slots, so without a total a package of small, high-ratio files
# could make one import decompress gigabytes. Two maximal templates, or many
# ordinary ones, fit.
MAX_FLOW_PACKAGE_TEMPLATES_UNPACKED_BYTES = 2 * MAX_TEMPLATE_UNCOMPRESSED_BYTES

__all__ = ["MAX_FLOW_PACKAGE_BYTES", "MAX_FLOW_PACKAGE_TEMPLATES_UNPACKED_BYTES"]
