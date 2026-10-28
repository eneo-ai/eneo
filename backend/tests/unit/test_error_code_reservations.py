from eneo.main.exceptions import ErrorCodes

MIGRATION_CODES: set[str] = set()  # migration PRs add their member names here


def test_reserved_migration_block_is_used_only_by_migration_codes():
    taken = {c.name for c in ErrorCodes if 9080 <= c.value <= 9089}
    assert taken <= MIGRATION_CODES
