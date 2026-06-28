import aiohttp


class AioHttpClient:
    session: aiohttp.ClientSession = None  # type: ignore[assignment]

    def start(self):
        self.session = aiohttp.ClientSession()

    async def stop(self):
        await self.session.close()
        self.session = None  # type: ignore[assignment]

    def __call__(self) -> aiohttp.ClientSession:
        assert self.session is not None
        return self.session


aiohttp_client = AioHttpClient()
