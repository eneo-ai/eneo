from __future__ import annotations

from enum import Enum


class FlowInputSource(str, Enum):
    FLOW_INPUT = "flow_input"
    PREVIOUS_STEP = "previous_step"
    ALL_PREVIOUS_STEPS = "all_previous_steps"
    HTTP_GET = "http_get"
    HTTP_POST = "http_post"


class AIBuilderInputSource(str, Enum):
    FLOW_INPUT = FlowInputSource.FLOW_INPUT.value
    PREVIOUS_STEP = FlowInputSource.PREVIOUS_STEP.value
    ALL_PREVIOUS_STEPS = FlowInputSource.ALL_PREVIOUS_STEPS.value


class FlowInputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    FILE = "file"
    ANY = "any"


class AIBuilderInputType(str, Enum):
    TEXT = FlowInputType.TEXT.value
    JSON = FlowInputType.JSON.value
    AUDIO = FlowInputType.AUDIO.value
    DOCUMENT = FlowInputType.DOCUMENT.value
    FILE = FlowInputType.FILE.value
    ANY = FlowInputType.ANY.value


class FlowOutputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"


class FlowOutputMode(str, Enum):
    PASS_THROUGH = "pass_through"
    HTTP_POST = "http_post"
    TRANSCRIBE_ONLY = "transcribe_only"
    TEMPLATE_FILL = "template_fill"


class AIBuilderOutputMode(str, Enum):
    PASS_THROUGH = FlowOutputMode.PASS_THROUGH.value
    TRANSCRIBE_ONLY = FlowOutputMode.TRANSCRIBE_ONLY.value
    TEMPLATE_FILL = FlowOutputMode.TEMPLATE_FILL.value


class FlowMcpPolicy(str, Enum):
    INHERIT = "inherit"
    RESTRICTED = "restricted"


class FlowRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStepResultStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStepAttemptStatus(str, Enum):
    STARTED = "started"
    RETRIED = "retried"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FlowRuntimeInputFormat(str, Enum):
    DOCUMENT = "document"
    AUDIO = "audio"
    FILE = "file"


class FlowTemplateAssetStatus(str, Enum):
    READY = "ready"
    NEEDS_ACTION = "needs_action"
    READ_ONLY = "read_only"
    UNAVAILABLE = "unavailable"
