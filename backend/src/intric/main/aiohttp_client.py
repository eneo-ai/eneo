import aiohttp


class AioHttpClient:
    session: aiohttp.ClientSession = None

    def start(self):
        # Configure timeout (per-request timeouts can override these)
        timeout = aiohttp.ClientTimeout(
            total=30.0,  # Maximum time for entire request
            connect=10.0,  # Maximum time to establish connection
        )

        # Configure TCP connector for connection pooling and cleanup
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool size
            limit_per_host=30,  # Max connections per host
            enable_cleanup_closed=True,  # Clean up closed connections
        )

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
        )

    async def stop(self):
        await self.session.close()
        self.session = None

    def __call__(self) -> aiohttp.ClientSession:
        assert self.session is not None
        return self.session


aiohttp_client = AioHttpClient()
