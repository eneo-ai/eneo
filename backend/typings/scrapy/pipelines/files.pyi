from collections.abc import Iterable
from typing import Any

from twisted.python.failure import Failure

from .. import Request
from ..http import Response

class FilesPipeline:
    def get_media_requests(self, item: object, info: object) -> Iterable[Request]: ...
    def media_failed(
        self,
        failure: Failure,
        request: object,
        info: object,
    ) -> dict[str, object] | None: ...
    def file_path(
        self,
        request: Request,
        response: Response | None = None,
        info: Any = None,
        *,
        item: Any = None,
    ) -> str: ...
