import aiohttp


class AioHttpClient:
    session: aiohttp.ClientSession | None = None

    def start(self) -> None:
        self.session = aiohttp.ClientSession()

    async def stop(self) -> None:
        session = self.session
        self.session = None
        if session is not None:
            await session.close()

    def __call__(self) -> aiohttp.ClientSession:
        assert self.session is not None
        return self.session


aiohttp_client = AioHttpClient()
