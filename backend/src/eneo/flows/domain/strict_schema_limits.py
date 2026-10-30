"""Provider limits on a schema sent as `strict: true`: one owner, data per provider.

A schema that satisfies the shape rules can still be refused for its size. Each
provider declares the limits it documents; the common limits are the field-wise
minimum over every declared provider, so one grammar holds on every route and a
provider without a declaration gets limits no declared provider exceeds.

OpenAI (structured outputs, "Supported schemas"):
https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas
- "up to 5000 object properties total, with up to 10 levels of nesting"
- "total string length of all property names, definition names, enum values, and const
  values cannot exceed 120,000 characters"
- "up to 1000 enum values across all enum properties"
- "For a single enum property with string values, the total string length of all enum
  values cannot exceed 15,000 characters when there are more than 250 enum values"
The page does not say whether an array counts as a nesting level; the predicate counts
it as one, which fails closed.

A provider that declares nothing gets the common limits, which equal the OpenAI values
while OpenAI is the only declared provider. That is not evidence about another route:
the per-route limits and a probe proof are V1.5c's to declare before any production
switch.

The eligibility grammar that reads these limits (first_strict_response_violation) is
deliberately narrower than what providers document. Rejected for now although the
OpenAI page supports them: pattern, format, numeric bounds and minItems/maxItems. Also
rejected: a nullable object or array, null inside an enum, and a const null.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class StrictSchemaLimits:
    max_nesting_levels: int
    max_properties: int
    max_enum_values: int
    # A single enum with more values than this is also bound by max_enum_string_chars.
    enum_size_checked_above_values: int
    max_enum_string_chars: int
    max_total_string_chars: int


# Keyed by canonical provider type (get_canonical_provider_type).
STRICT_SCHEMA_LIMITS_BY_PROVIDER: Mapping[str, StrictSchemaLimits] = {
    "openai": StrictSchemaLimits(
        max_nesting_levels=10,
        max_properties=5000,
        max_enum_values=1000,
        enum_size_checked_above_values=250,
        max_enum_string_chars=15_000,
        max_total_string_chars=120_000,
    ),
}


def _common_limits(
    declared: Mapping[str, StrictSchemaLimits],
) -> StrictSchemaLimits:
    return StrictSchemaLimits(
        **{
            field.name: min(getattr(limits, field.name) for limits in declared.values())
            for field in fields(StrictSchemaLimits)
        }
    )


COMMON_STRICT_SCHEMA_LIMITS = _common_limits(STRICT_SCHEMA_LIMITS_BY_PROVIDER)


def strict_schema_limits_for(provider_type: str) -> StrictSchemaLimits:
    return STRICT_SCHEMA_LIMITS_BY_PROVIDER.get(
        provider_type, COMMON_STRICT_SCHEMA_LIMITS
    )
