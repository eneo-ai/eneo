import aiohttp

from eneo.crawler.destination_policy import DestinationPolicy, PolicyResolver
from eneo.main.config import LOOPBACK_HOSTS, get_settings

# Every call through the shared session ends after this many seconds. Only
# calls to identity providers use it, and none may hold a request longer.
REQUEST_TIMEOUT_SECONDS = 5

# Where a call to a provider may connect: private networks yes (the operator
# chooses the provider), never link-local, metadata or IPv4-in-IPv6
# addresses, and loopback only as ``loopback_allowed`` says.
PROVIDER_POLICY = DestinationPolicy(block_private_networks=False)


def loopback_allowed() -> bool:
    """Whether a provider may be on this machine: in development only.

    Elsewhere an administrator who can change the sign-in settings could point
    the backend at its own loopback services.
    """
    return get_settings().is_development


class AioHttpClient:
    session: aiohttp.ClientSession | None = None
    _resolver: PolicyResolver | None = None

    def start(self) -> None:
        # The policy is checked on the addresses a connection uses, so a name
        # cannot rebind between a check and the connection. aiohttp skips the
        # resolver for an IP literal; the provider requests check those.
        self._resolver = PolicyResolver(
            PROVIDER_POLICY,
            loopback_names=LOOPBACK_HOSTS if loopback_allowed() else (),
        )
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=self._resolver),
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
        )

    async def stop(self) -> None:
        session = self.session
        self.session = None
        if session is not None:
            await session.close()
        # The connector does not own a resolver it was given.
        if self._resolver is not None:
            await self._resolver.close()
            self._resolver = None

    def __call__(self) -> aiohttp.ClientSession:
        assert self.session is not None
        return self.session


aiohttp_client = AioHttpClient()
