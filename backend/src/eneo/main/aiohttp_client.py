import aiohttp


class AioHttpClient:
    session: aiohttp.ClientSession | None = None

    def start(self):
        self.session = aiohttp.ClientSession()

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
