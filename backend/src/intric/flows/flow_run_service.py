"""Compatibility shim for the Flow run application service."""

from __future__ import annotations

import sys
from typing import Any

from intric.flows.application import flow_run_service as _flow_run_service
from intric.flows.application.flow_run_service import FlowRunService as _FlowRunService

logger = _flow_run_service.logger


class FlowRunService(_FlowRunService):
    async def create_run(self, *args: Any, **kwargs: Any):
        _flow_run_service.logger = sys.modules[__name__].logger
        return await super().create_run(*args, **kwargs)


FlowRunService.__module__ = _FlowRunService.__module__

__all__ = ["FlowRunService"]
