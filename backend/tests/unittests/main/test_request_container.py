"""The request container: Container's providers, copied when a request first uses them."""

from typing import Any, Callable
from uuid import uuid4

import pytest
from dependency_injector import containers, errors, providers

from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.main.container.request_container import request_container
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB


def _user() -> UserInDB:
    tenant = TenantInDB.model_construct(id=uuid4())
    return UserInDB.model_construct(id=uuid4(), tenant_id=tenant.id, tenant=tenant)


def _lazy_contract_breaches(
    declared: type[containers.DeclarativeContainer],
) -> set[str]:
    """What building a declared container does beyond copying its providers.

    A request container only copies. Each breach names a piece of work it
    would skip: wiring, loading configuration, applying a nested container's
    overrides, binding ``__self__``, or a resource with a lifetime of its own.
    """
    reached = list(declared.traverse())
    breaches: set[str] = set()
    if any(isinstance(provider, providers.BaseResource) for provider in reached):
        breaches.add("resource")
    if any(isinstance(provider, providers.Self) for provider in reached):
        breaches.add("consumes __self__")
    if any(isinstance(provider, providers.Container) for provider in reached):
        breaches.add("nested container")
    if declared.wiring_config.modules or declared.wiring_config.packages:
        breaches.add("wiring")
    if any(
        config.get_ini_files()
        or config.get_yaml_files()
        or config.get_json_files()
        or config.get_pydantic_settings()
        for config in reached
        if isinstance(config, providers.Configuration)
    ):
        breaches.add("configuration to load")
    return breaches


def test_building_container_does_nothing_that_copying_on_first_use_skips() -> None:
    class _Inner(containers.DeclarativeContainer):
        value = providers.Object(1)

    class _Breaching(containers.DeclarativeContainer):
        wiring_config = containers.WiringConfiguration(modules=["eneo.main"])
        __self__ = providers.Self()
        config = providers.Configuration(yaml_files=["settings.yaml"])
        resource = providers.Resource(dict)
        consumer = providers.Factory(dict, container=__self__)
        inner = providers.Container(_Inner)

    assert _lazy_contract_breaches(_Breaching) == {
        "resource",
        "consumes __self__",
        "nested container",
        "wiring",
        "configuration to load",
    }
    assert _lazy_contract_breaches(Container) == set()


def _shape(provider: object, names: dict[int, str], *, top: bool = False) -> object:
    """A provider as its type, what it provides and what it is given, with
    every provider it is given named after the container's own provider."""
    if not isinstance(provider, providers.Provider):
        return provider
    if not top and id(provider) in names:
        return names[id(provider)]
    overridden = tuple(_shape(each, names) for each in provider.overridden)
    if isinstance(provider, providers.Dependency):
        return (
            type(provider),
            provider.instance_of,
            _shape(provider.default, names),
            overridden,
        )
    if isinstance(provider, providers.Configuration):
        return (type(provider), provider.get_name(), overridden)
    if isinstance(provider, providers.AttributeGetter):
        return (type(provider), _shape(provider.provides, names), provider.name)
    if isinstance(provider, providers.ProvidedInstance):
        return (type(provider), _shape(provider.provides, names))
    if isinstance(provider, providers.Object):
        return (type(provider), provider.provides, overridden)
    assert isinstance(
        provider, (providers.Callable, providers.Factory, providers.BaseSingleton)
    ), f"Describe {type(provider).__name__} here before Container declares one."
    attributes: dict[str, Any] = getattr(provider, "attributes", {})
    return (
        type(provider),
        provider.provides,
        tuple(_shape(argument, names) for argument in provider.args),
        {name: _shape(value, names) for name, value in provider.kwargs.items()},
        {name: _shape(value, names) for name, value in attributes.items()},
        overridden,
    )


def _shapes(container: containers.Container) -> dict[str, object]:
    for name in Container.providers:
        getattr(container, name)
    named = {id(provider): name for name, provider in container.providers.items()}
    return {
        name: _shape(container.providers[name], named, top=True)
        for name in Container.providers
    }


def test_every_provider_a_request_resolves_is_the_one_container_builds() -> None:
    copied_alone = containers.DynamicContainer()
    for name, provider in Container.providers.items():
        copied_alone.set_provider(name, providers.deepcopy(provider))

    expected = _shapes(Container())

    assert _shapes(request_container()) == expected
    # Copies that share no memo point at copies of their dependencies, not at
    # the container's own providers, and the comparison sees it.
    assert _shapes(copied_alone) != expected


def test_a_constructor_override_reaches_a_repo_resolved_later() -> None:
    session = object()
    container = request_container(session=providers.Object(session))

    assert container.flow_repo().session is session


def test_a_user_set_after_a_provider_was_first_used_reaches_that_provider() -> None:
    container = request_container(session=providers.Object(object()))
    assembler = container.prompt_assembler
    user = _user()

    override_user(container=container, user=user)

    assert container.prompt_assembler is assembler
    assert assembler().user is user


def test_a_provider_reached_through_another_is_the_one_touched_by_name() -> None:
    session = object()
    container = request_container(session=providers.Object(session))
    reached = container.flow_run_access_policy.kwargs["flow_repo"]

    assert "flow_repo" not in container.providers
    assert container.flow_repo is reached
    assert container.flow_repo().session is session


def test_a_singleton_is_one_per_request_container() -> None:
    first, second = request_container(), request_container()

    assert first.encryption_service() is first.encryption_service()
    assert first.encryption_service() is not second.encryption_service()


def test_an_override_stays_in_its_request_container() -> None:
    first, second = request_container(), request_container()
    user, service = _user(), object()
    class_overrides = (Container.user.overridden, Container.user_service.overridden)

    override_user(container=first, user=user)
    first.user_service.override(providers.Object(service))

    assert first.user() is user and first.user_service() is service
    assert second.user.overridden == ()
    assert second.user_service.overridden == ()
    assert (Container.user.overridden, Container.user_service.overridden) == (
        class_overrides
    )


def test_a_class_override_applies_when_the_request_first_uses_the_provider() -> None:
    """Container copies every provider when it is built; a request container
    copies one when the request first uses it, class-level overrides included."""
    built_before = Container()
    container = request_container()
    replacement, later = object(), object()

    with Container.encryption_service.override(providers.Object(replacement)):
        assert built_before.encryption_service() is not replacement
        assert container.encryption_service() is replacement
        with Container.encryption_service.override(providers.Object(later)):
            assert container.encryption_service() is replacement


@pytest.mark.parametrize("build", [Container, request_container])
def test_an_undefined_request_root_is_named_as_container_names_it(
    build: Callable[..., Container],
) -> None:
    container = build(session=providers.Object(object()))

    with pytest.raises(
        errors.Error, match='Dependency "Container.user" is not defined'
    ):
        container.prompt_assembler()


def test_a_request_container_refuses_a_deep_copy() -> None:
    container = request_container(session=providers.Object("S"))

    with pytest.raises(TypeError, match="not deep-copyable"):
        providers.deepcopy(container)
    # Container itself still deep-copies, so the refusal is the request container's.
    copied = providers.deepcopy(Container(session=providers.Object("S")))
    assert copied.flow_repo().session == "S"
