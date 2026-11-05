"""A request's container: Container's providers, copied on first use.

``Container(...)`` deep-copies every provider it declares when it is built,
while a request uses a few dozen of them. A request container copies a
provider, with the subgraph it reaches, the first time the request touches it,
into one memo per request; only the request roots (``Container``'s Dependency
providers) are copied when it is built. Its contract:

- every provider a request touches is a private per-request copy;
- Singletons are one per request;
- an override made on the request container stays in that request;
- the class-level providers are never mutated;
- a class-level override is copied when the request first touches the
  provider, not when the container is built;
- ``providers``, ``traverse()`` and ``reset_singletons()`` see only the
  providers the request touched, and nothing in src relies on them;
- a request container is not deep-copyable; build another.

``Container`` stays the only owner of provider definitions.
"""

from typing import Any, Self, cast

from dependency_injector import containers, providers

from eneo.main.container.container import Container


class RequestContainer(containers.DynamicContainer):
    __self__: providers.Self["RequestContainer"]

    def __init__(self, **overriding_providers: providers.Provider[Any]) -> None:
        super().__init__()
        self.declarative_parent = Container
        self._copies: dict[int, Any] = {id(Container.__self__): self.__self__}
        # A Dependency names itself through the container that holds it.
        # Holding the request roots from the start keeps an undefined one
        # reported as Container reports it, instead of failing to name itself.
        for name in Container.dependencies:
            getattr(self, name)
        self.override_providers(**overriding_providers)

    def __getattr__(self, name: str) -> providers.Provider[Any]:
        # Called only for an attribute not yet set: a provider's first touch.
        provider = None if name.startswith("_") else Container.providers.get(name)
        if provider is None:
            raise AttributeError(name)
        copied = providers.deepcopy(provider, self._copies)
        self.set_provider(name, copied)
        return copied

    def __deepcopy__(self, memo: dict[str, Any] | None) -> Self:
        # A copy would hold build-time roots its later first touches bind to.
        raise TypeError("A request container is not deep-copyable; build another.")


def request_container(**overriding_providers: providers.Provider[Any]) -> Container:
    """Build a request's container, typed as the Container it stands in for."""
    return cast(Container, RequestContainer(**overriding_providers))
