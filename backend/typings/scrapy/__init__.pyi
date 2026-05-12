
from typing import Any

from . import crawler as crawler
from . import exceptions as exceptions
from . import http as http
from . import linkextractors as linkextractors
from . import spiders as spiders

class Request:
    url: str
    meta: dict[str, Any]
