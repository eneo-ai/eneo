import aiohttp

# Every call through the shared session ends after this many seconds. Only
# calls to identity providers use it, and none may hold a request longer.
REQUEST_TIMEOUT_SECONDS = 5


class AioHttpClient:
    session: aiohttp.ClientSession | None = None

    def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        )

    async def stop(self):
        # A worker whose start failed is shut down again after this ran.
        if self.session is None:
            return
        await self.session.close()
        self.session = None

    def __call__(self) -> aiohttp.ClientSession:
        assert self.session is not None
        return self.session


aiohttp_client = AioHttpClient()
