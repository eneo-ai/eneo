"""Unit tests for the page-progress lifecycle fact.

This is the typed predicate that watchdog Phase 3.5 uses to detect early zombies
(IN_PROGRESS crawls that crashed before recording any page progress). Naming the
predicate inside the domain module prevents the watchdog SQL from drifting from
the operational definition of "no page progress".
"""

from __future__ import annotations

import sqlalchemy as sa

from intric.database.tables.websites_table import CrawlRuns
from intric.websites.domain.crawl_lifecycle import (
    has_no_page_progress,
    no_page_progress_sql_predicate,
)


def test_has_no_page_progress_true_for_unrecorded_pages():
    assert has_no_page_progress(pages_crawled=None) is True


def test_has_no_page_progress_true_for_zero_pages():
    assert has_no_page_progress(pages_crawled=0) is True


def test_has_no_page_progress_false_for_one_page():
    assert has_no_page_progress(pages_crawled=1) is False


def test_has_no_page_progress_false_for_large_page_count():
    assert has_no_page_progress(pages_crawled=999) is False


def test_no_page_progress_sql_predicate_matches_inline_or_expression():
    """The helper must compile to byte-identical SQL as the canonical inline
    expression that Phase 3.5 watchdog SQL used before this predicate had a
    named owner. Asserting full SQL equality (not substring containment)
    catches predicate logic flips a substring assertion would miss, e.g.
    accidentally swapping OR for AND or adding an extra clause."""
    actual = no_page_progress_sql_predicate(CrawlRuns.pages_crawled)
    expected = sa.or_(CrawlRuns.pages_crawled.is_(None), CrawlRuns.pages_crawled == 0)

    actual_sql = str(actual.compile(compile_kwargs={"literal_binds": True}))
    expected_sql = str(expected.compile(compile_kwargs={"literal_binds": True}))
    assert actual_sql == expected_sql
