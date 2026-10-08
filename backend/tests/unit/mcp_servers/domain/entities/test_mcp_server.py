"""Capability helpers on the MCP server entity module."""

from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
    MCPServerBackingModel,
    duplicate_capability_purposes,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)


class TestDuplicateCapabilityPurposes:
    def test_general_servers_never_count(self):
        assert duplicate_capability_purposes(["general", "general", None]) == []

    def test_one_marker_per_purpose_is_clean(self):
        assert duplicate_capability_purposes(list(CAPABILITY_PURPOSES)) == []

    def test_repeated_purposes_are_reported_once_in_first_seen_order(self):
        first, second = CAPABILITY_PURPOSES[0], CAPABILITY_PURPOSES[1]
        purposes = [second, first, second, "general", first, second]

        assert duplicate_capability_purposes(purposes) == [second, first]


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"klass {level}",
        security_level=level,
        security_enabled=True,
    )


def _backing_model(
    *,
    enabled: bool = True,
    deleted: bool = False,
    classification: SecurityClassification | None = None,
) -> MCPServerBackingModel:
    return MCPServerBackingModel(
        id=uuid4(),
        name="gpt-image-1",
        nickname="GPT Image",
        provider_name="OpenAI",
        is_enabled=enabled,
        is_deleted=deleted,
        security_classification=classification,
    )


def _server(**kwargs) -> MCPServer:
    return MCPServer(
        tenant_id=uuid4(),
        name="provider",
        http_url="http://provider.example/mcp",
        purpose="image_generation",
        **kwargs,
    )


class TestEffectiveSecurityClassification:
    def test_own_classification_wins(self):
        own = _classification(2)
        server = _server(
            security_classification=own,
            image_model=_backing_model(classification=_classification(3)),
        )

        assert server.effective_security_classification is own

    def test_builtin_provider_inherits_from_its_image_model(self):
        inherited = _classification(3)
        server = _server(image_model=_backing_model(classification=inherited))

        assert server.effective_security_classification is inherited

    def test_nothing_to_inherit_yields_none(self):
        assert _server().effective_security_classification is None
        assert (
            _server(image_model=_backing_model()).effective_security_classification
            is None
        )


class TestIsBackingModelAvailable:
    def test_external_server_has_no_backing_model_to_block_it(self):
        assert _server().is_backing_model_available is True

    def test_enabled_live_model_is_available(self):
        assert _server(image_model=_backing_model()).is_backing_model_available

    def test_disabled_or_deleted_model_makes_the_provider_unavailable(self):
        assert not _server(
            http_auth_type="internal", image_model=_backing_model(enabled=False)
        ).is_backing_model_available
        assert not _server(
            http_auth_type="internal", image_model=_backing_model(deleted=True)
        ).is_backing_model_available


class TestIsInternal:
    """Internal-ness is a property of how the server was built, never of its
    name, so an admin-registered server cannot pass as one of Eneo's own."""

    def _server(self, **kwargs) -> MCPServer:
        base = dict(tenant_id=uuid4(), name="knowledge", http_url="http://x/mcp")
        return MCPServer(**{**base, **kwargs})

    def test_loopback_factory_servers_are_internal(self):
        assert self._server(is_internal=True).is_internal is True

    def test_builtin_provider_rows_are_internal(self):
        server = self._server(
            name="Image Studio",
            http_auth_type="internal",
            purpose="image_generation",
            image_model_id=uuid4(),
        )
        assert server.is_internal is True

    def test_external_server_named_like_an_internal_one_is_not_internal(self):
        assert self._server(name="knowledge").is_internal is False
        assert self._server(name="files", http_auth_type="bearer").is_internal is False

    def test_flag_follows_an_auth_type_change(self):
        server = self._server(http_auth_type="internal", purpose="image_generation")
        server.http_auth_type = "bearer"
        assert server.is_internal is False

    def test_bundled_rows_are_built_into_eneo_whatever_their_name(self):
        bundled = self._server(name="Fråga fil", http_auth_type="bundled")
        assert bundled.is_bundled is True
        assert bundled.is_internal is False
        assert self._server(name="Built into Eneo").is_bundled is False
