from __future__ import annotations

from enum import StrEnum, unique

from eneo.main.exceptions import BadRequestException


@unique
class FlowAuthoringRefusalCode(StrEnum):
    FLOW_IS_PUBLISHED = "flow_is_published"
    FLOW_SPACE_MISMATCH = "flow_space_mismatch"
    INVALID_EXISTING_STEP_REF = "invalid_existing_step_ref"
    ARCHITECTURE_MATERIALIZATION_FAILED = "architecture_materialization_failed"
    # A model or knowledge reference that is not written as a slot reference.
    INVALID_MODEL_REF = "invalid_model_ref"
    INVALID_KB_REF = "invalid_kb_ref"
    # Two steps share the assistant a change would rewrite. The refusal has no
    # code of its own on the wire: its value is the general one.
    ASSISTANT_SHARED_BY_STEPS = "bad_request"


class FlowAuthoringRefusalException(BadRequestException):
    """A refusal of the authoring command that no Flows endpoint answers.

    The package import builds a create with no template attachment, and its
    reader has by then refused a draft with an existing-step reference or a
    malformed resource reference, so none of these can reach it, which is why
    these are not in the public Flow error catalogue. Three refuse an edit of an existing flow (published, another
    space, a shared assistant); the others can refuse a create as well.
    """

    code: FlowAuthoringRefusalCode

    def __init__(
        self,
        message: str,
        *,
        code: FlowAuthoringRefusalCode,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code.value, context=context)
        self.code = code
