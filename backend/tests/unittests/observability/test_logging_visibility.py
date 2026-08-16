"""Importing eneo.main.logging must never silence loggers it does not own.

Application modules log through ``get_logger``: a parentless SimpleLogger that
owns its handler, which is why ``caplog`` (a root handler) never sees it. The
tests below drive each module's logger through its own configured handler and
formatter instead.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from eneo.flows.ai_builder import (
    ai_builder_conversation_compaction,
    ai_builder_create_compiler,
    ai_builder_new_step_compiler,
    ai_builder_schema_evidence,
    ai_builder_source_reader_contracts,
)
from eneo.flows.ai_builder.ai_builder_assembly import create as assembly_create
from eneo.flows.ai_builder.ai_builder_assembly import lower as assembly_lower
from eneo.flows.ai_builder.ai_builder_assembly.document_report import (
    lowering as document_report_lowering,
)
from eneo.main.logging import OTELJSONFormatter, SimpleLogger


@pytest.mark.parametrize("name", ["asyncio", "eneo", "eneo.flows"])
def test_import_leaves_pre_registered_loggers_at_their_own_level(name: str):
    """Regression guard for the deleted import-time sweep.

    These names are registered (or placeholders) before ``eneo.main.logging``
    is imported in any process; the sweep used to force them to CRITICAL.
    """

    logger = logging.getLogger(name)
    assert logger.level == logging.NOTSET
    assert logger.isEnabledFor(logging.ERROR)


@pytest.mark.parametrize(
    "module",
    [
        ai_builder_conversation_compaction,
        ai_builder_create_compiler,
        ai_builder_new_step_compiler,
        ai_builder_schema_evidence,
        ai_builder_source_reader_contracts,
        assembly_create,
        assembly_lower,
        document_report_lowering,
    ],
)
def test_ai_builder_module_records_reach_the_application_handler(module):
    logger = module.logger
    assert isinstance(logger, SimpleLogger)
    handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert handlers, f"{module.__name__} logger owns no stream handler"
    handler = handlers[0]

    buffer = io.StringIO()
    previous_stream = handler.setStream(buffer)
    try:
        # Emit at the severity this deployment's LOGLEVEL already admits, so the
        # test proves the configured path rather than a level it rewrote.
        logger.log(
            max(logger.level, handler.level, logging.INFO),
            "visibility_sentinel",
            extra={"probe": module.__name__},
        )
    finally:
        if previous_stream is not None:
            handler.setStream(previous_stream)

    line = buffer.getvalue().strip()
    assert "visibility_sentinel" in line
    if isinstance(handler.formatter, OTELJSONFormatter):
        payload = json.loads(line)
        assert payload["body"] == "visibility_sentinel"
        assert payload["attributes"]["probe"] == module.__name__
