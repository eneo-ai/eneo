"""The runtime check of a step's input or output value against its contract.

Every runtime path that checks a step's value against its input or output
contract calls ``check_contract_in_child``. It runs the check in the killable
contract checker process (tool_argument_check), so a contract whose matching
holds the GIL ends at the check's time limit instead of holding the worker's
event loop, which every run's heartbeat shares.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import ContractSide
from eneo.flows.output_processing import raise_contract_finding
from eneo.flows.runtime.tool_argument_check import (
    ArgumentCheckUnfinished,
    ToolArgumentsNotJson,
    check_contract_value,
)
from eneo.json_types import JsonValue
from eneo.main.exceptions import TypedIOValidationException

# A value that cannot be written as JSON is the step's input on the input side
# and the model's answer on the output side.
_NOT_JSON_CODE: Mapping[ContractSide, FlowApiErrorCode] = MappingProxyType(
    {
        "input": FlowApiErrorCode.TYPED_IO_INVALID_JSON_INPUT,
        "output": FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED,
    }
)


def not_checked_message(
    label: str, subject: str, target: str, *, timed_out: bool
) -> str:
    """The message of typed_io_contract_not_checked: a check that did not
    finish says nothing about whether ``subject`` fits ``target``."""
    return (
        f"{label}: {subject} could not be checked against {target}"
        + (
            " within the time limit, which a larger value or a contract "
            "with more work per item reaches sooner"
            if timed_out
            else ""
        )
        + "; it was not found invalid."
    )


async def check_contract_in_child(
    value: JsonValue,
    schema: Mapping[str, object],
    *,
    label: str,
    side: ContractSide,
) -> None:
    """Check ``value`` in the contract checker process. A violation or an
    unevaluable contract raises what validate_against_contract raises for it;
    a value that cannot be written as JSON raises its side's not-JSON code; a
    check that does not finish within its limit, or raises there, raises
    typed_io_contract_not_checked."""
    try:
        finding = await check_contract_value(value, schema)
    except ToolArgumentsNotJson:
        raise TypedIOValidationException(
            f"{label}: the value is not JSON (a NaN, an infinity, or nesting "
            "too deep), so it cannot be checked against the contract.",
            code=_NOT_JSON_CODE[side].value,
        ) from None
    if isinstance(finding, ArgumentCheckUnfinished):
        raise TypedIOValidationException(
            not_checked_message(
                label,
                "the value",
                "the contract",
                timed_out=finding.timed_out,
            ),
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_NOT_CHECKED.value,
        )
    raise_contract_finding(finding, schema, label=label, side=side)
