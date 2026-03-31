"""Compatibility module alias for flow dispatch helpers."""

from __future__ import annotations

import sys

from intric.flows.application import flow_dispatch as _flow_dispatch_module

sys.modules[__name__] = _flow_dispatch_module
