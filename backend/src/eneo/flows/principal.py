"""Compatibility exports for the platform authentication principal."""

from eneo.authentication.principal import Principal as FlowPrincipal
from eneo.authentication.principal import (
    PrincipalAuditActorFields as FlowAuditActorFields,
)

__all__ = ["FlowAuditActorFields", "FlowPrincipal"]
