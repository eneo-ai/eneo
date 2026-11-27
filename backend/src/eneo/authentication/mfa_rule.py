"""The organisation's rule for what counts as MFA at its identity provider.

The provider decides whether a person used a second factor and says so in the
signed ID token, in ``acr`` (an agreed value) or in ``amr`` (the methods used).
Providers differ, so Eneo does not guess: the organisation states which claim
its provider uses and which values mean MFA. Eneo compares and stores the
answer, yes or no, on the session. It never lists methods of its own and keeps
none of the claims.

The organisation can also state how Eneo asks the provider for MFA when a
person signs in for it: ``acr_values``, or ``claims`` with ``acr`` as an
essential claim. A provider that always requires MFA for Eneo's client needs
only the rule.

The rule lives in the organisation's sign-in settings under ``mfa``. This
module alone reads and writes that form.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from eneo.authentication.oidc.verification import VerifiedAuthentication
from eneo.main.logging import get_logger

logger = get_logger(__name__)

MfaClaim = Literal["acr", "amr"]
# How Eneo asks for MFA (OpenID Connect Core 3.1.2.1 and 5.5).
MfaRequest = Literal["acr_values", "claims"]

# Where the rule sits in the organisation's sign-in settings.
MFA_RULE_KEY = "mfa"


@dataclass(frozen=True)
class MfaRule:
    """Which claim says MFA, and with which values.

    ``acr``: the token's value must be one of ``values``.
    ``amr``: the token must name every one of ``values``; more methods than
    those do not matter.

    ``request`` is how Eneo asks for MFA, by the ``acr`` values of the rule,
    most wanted first. Only an ``acr`` rule has values to ask for.
    """

    claim: MfaClaim
    values: tuple[str, ...]
    request: MfaRequest | None = None

    def __post_init__(self) -> None:
        # An empty amr rule would be met by every token, and an empty acr rule
        # by none: neither is a rule.
        if not self.values or not all(self.values):
            raise ValueError("An MFA rule names at least one value, none empty")
        if len(set(self.values)) != len(self.values):
            raise ValueError("An MFA rule names each value once")
        if any(value != value.strip() or " " in value for value in self.values):
            # acr_values is a space-separated list, and no provider's acr or
            # amr value holds a space.
            raise ValueError("An MFA rule's values hold no spaces")
        if self.request is not None and self.claim != "acr":
            raise ValueError("Eneo can ask for MFA only by the values of an acr rule")

    def accepts(self) -> tuple[MfaClaim, frozenset[str]]:
        """What counts as MFA under the rule, whatever order it was written
        in and however Eneo asks. Two rules that accept the same are the same
        rule to a session that met one of them."""
        return self.claim, frozenset(self.values)

    def authorization_parameters(self) -> dict[str, str]:
        """What to add to the authorization request to ask for MFA."""
        if self.request == "acr_values":
            return {"acr_values": " ".join(self.values)}
        if self.request == "claims":
            asked = {"acr": {"essential": True, "values": list(self.values)}}
            return {"claims": json.dumps({"id_token": asked}, separators=(",", ":"))}
        return {}

    def met_by(self, verified: VerifiedAuthentication) -> bool:
        """Whether a verified sign-in says MFA under this rule.

        A claim the provider left out, or sent in a form Eneo could not trust
        (and so counts as missing), means no.
        """
        if self.claim == "acr":
            return verified.acr is not None and verified.acr in self.values
        return verified.amr is not None and set(self.values) <= set(verified.amr)

    def as_config(self) -> dict[str, object]:
        stored: dict[str, object] = {"claim": self.claim, "values": list(self.values)}
        if self.request is not None:
            stored["request"] = self.request
        return stored

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "MfaRule | None":
        """The rule the sign-in settings state; None when they state none.

        A stored rule that cannot be read is no rule: nobody gets MFA under
        it, which an administrator notices, instead of everybody.
        """
        stored = config.get(MFA_RULE_KEY)
        if stored is None:
            return None
        try:
            if not isinstance(stored, Mapping):
                raise ValueError("The MFA rule is not an object")
            rule = cast(Mapping[str, object], stored)
            claim, values = rule.get("claim"), rule.get("values")
            if claim not in ("acr", "amr"):
                raise ValueError("The MFA rule names neither acr nor amr")
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in cast(list[object], values)
            ):
                raise ValueError("The MFA rule's values are not a list of text")
            request = rule.get("request")
            if request not in (None, "acr_values", "claims"):
                raise ValueError("The MFA rule asks in a way Eneo does not know")
            return cls(
                claim=claim, values=tuple(cast(list[str], values)), request=request
            )
        except ValueError as exc:
            # The reason only: the stored value is an administrator's setting,
            # but a broken one is not worth quoting.
            logger.error("mfa_rule_unreadable", extra={"reason": str(exc)})
            return None
