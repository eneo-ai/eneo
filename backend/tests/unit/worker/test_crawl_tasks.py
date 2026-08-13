from eneo.worker.crawl_tasks import _stale_titles_for_crawl, _validator_refresh


def test_partial_crawl_never_marks_missing_titles_stale() -> None:
    assert (
        _stale_titles_for_crawl(
            ["https://k.se/seen", "https://k.se/missing"],
            {"https://k.se/seen"},
            set(),
            is_partial=True,
        )
        == []
    )


def test_complete_crawl_excludes_seen_and_failed_titles_from_stale_cleanup() -> None:
    assert _stale_titles_for_crawl(
        ["seen", "failed", "stale"],
        {"seen"},
        {"failed"},
        is_partial=False,
    ) == ["stale"]


def test_validator_refresh_records_changed_values() -> None:
    assert _validator_refresh(
        title="https://k.se/a",
        stored=('"old"', "Mon, 01 Jun 2026 10:00:00 GMT"),
        etag='"new"',
        last_modified="Tue, 02 Jun 2026 10:00:00 GMT",
    ) == {
        "b_title": "https://k.se/a",
        "b_etag": '"new"',
        "b_last_modified": "Tue, 02 Jun 2026 10:00:00 GMT",
    }


def test_validator_refresh_records_validator_removal() -> None:
    assert _validator_refresh(
        title="https://k.se/a",
        stored=('"old"', "Mon, 01 Jun 2026 10:00:00 GMT"),
        etag=None,
        last_modified=None,
    ) == {
        "b_title": "https://k.se/a",
        "b_etag": None,
        "b_last_modified": None,
    }


def test_validator_refresh_skips_identical_values() -> None:
    assert (
        _validator_refresh(
            title="https://k.se/a",
            stored=('"same"', None),
            etag='"same"',
            last_modified=None,
        )
        is None
    )
