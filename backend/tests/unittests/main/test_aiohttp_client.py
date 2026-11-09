from eneo.main.aiohttp_client import AioHttpClient


async def test_a_second_stop_does_nothing() -> None:
    """A worker whose start failed after closing the client is shut down
    again; the second stop must not hide the reason with its own error."""
    client = AioHttpClient()
    client.start()

    await client.stop()
    await client.stop()

    assert client.session is None
