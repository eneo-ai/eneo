from typing import Any

from .. import Request
from ..http import Response

class FilesPipeline:
    def file_path(
        self,
        request: Request,
        response: Response | None = None,
        info: Any = None,
        *,
        item: Any = None,
    ) -> str: ...

