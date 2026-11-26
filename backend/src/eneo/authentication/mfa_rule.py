"""The organisation's rule for what counts as MFA at its identity provider.

The provider decides whether a person used a second factor and says so in the
signed ID token, in ``acr`` (an agreed value) or in ``amr`` (the methods used).
Providers differ, so Eneo does not guess: the organisation states which claim
its provider uses and which values mean MFA. Eneo compares and stores the
answer, yes or no, on the session. It never lists methods of its own and keeps
none of the claims.

The rule lives in the organisation's sign-in settings under ``mfa``. This
module alone reads that form.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from eneo.authentication.oidc.verification import VerifiedAuthentication
from eneo.main.logging import get_logger

logger = get_logger(__name__)

MfaClaim = Literal["acr", "amr"]

# Where the rule sits in the organisation's sign-in settings.
MFA_RULE_KEY = "mfa"


@dataclass(frozen=True)
class MfaRule:
    """Which claim says MFA, and with which values.

    ``acr``: the token's value must be one of ``values``.
    ``amr``: the token must name every one of ``values``; more methods than
    those do not matter.
    """

    claim: MfaClaim
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        # An empty amr rule would be met by every token, and an empty acr rule
        # by none: neither is a rule.
        if not self.values or not all(self.values):
            raise ValueError("An MFA rule names at least one value, none empty")
        if len(set(self.values)) != len(self.values):
            raise ValueError("An MFA rule names each value once")

    def met_by(self, verified: VerifiedAuthentication) -> bool:
        """Whether a verified sign-in says MFA under this rule.

        A claim the provider left out, or sent in a form Eneo could not trust
        (and so counts as missing), means no.
        """
        if self.claim == "acr":
            return verified.acr is not None and verified.acr in self.values
        return verified.amr is not None and set(self.values) <= set(verified.amr)

    def as_config(self) -> dict[str, object]:
        return {"claim": self.claim, "values": list(self.values)}

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
            return cls(claim=claim, values=tuple(cast(list[str], values)))
        except ValueError as exc:
            # The reason only: the stored value is an administrator's setting,
            # but a broken one is not worth quoting.
            logger.error("mfa_rule_unreadable", extra={"reason": str(exc)})
            return None
