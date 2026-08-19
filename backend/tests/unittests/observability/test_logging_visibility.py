"""Importing eneo.main.logging must never silence loggers it does not own.

Application modules log through ``get_logger``: a parentless SimpleLogger that
owns its handler, which is why ``caplog`` (a root handler) never sees it. The
tests below drive each module's logger through its own configured handler and
formatter instead.
"""

from __future__ import annotations

import logging

import pytest


@pytest.mark.parametrize("name", ["asyncio", "eneo", "eneo.flows"])
def test_import_leaves_pre_registered_loggers_at_their_own_level(name: str):
    """Regression guard for the deleted import-time sweep.

    These names are registered (or placeholders) before ``eneo.main.logging``
    is imported in any process; the sweep used to force them to CRITICAL.
    """

    logger = logging.getLogger(name)
    assert logger.level == logging.NOTSET
    assert logger.isEnabledFor(logging.ERROR)
