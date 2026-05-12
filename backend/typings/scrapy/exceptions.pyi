class StopDownload(Exception):
    fail: bool

    def __init__(self, *, fail: bool = True) -> None: ...
