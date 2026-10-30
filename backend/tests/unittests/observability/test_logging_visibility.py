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

from eneo.flows import flow_document_limits, flow_runtime_policy, flow_settings
from eneo.flows.runtime import docx_template_runtime, remote_transcription
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
        flow_document_limits,
        flow_runtime_policy,
        flow_settings,
        docx_template_runtime,
        remote_transcription,
    ],
)
def test_flow_module_records_reach_the_application_handler(module):
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


def test_a_level_change_applies_to_a_logger_that_already_logged():
    """A SimpleLogger is not registered with logging's manager, so the
    manager's cache clearing on setLevel never reaches it: a level read once
    must not outlive a later setLevel."""
    logger = SimpleLogger(
        name="eneo.tests.level_change", level=logging.INFO, console=False
    )
    records: list[logging.LogRecord] = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)

    logger.debug("before")
    logger.setLevel(logging.DEBUG)
    logger.debug("after")
    logger.setLevel(logging.INFO)
    logger.debug("hidden again")

    assert [record.getMessage() for record in records] == ["after"]
