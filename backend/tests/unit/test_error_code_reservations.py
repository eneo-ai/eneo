from eneo.main.exceptions import ErrorCodes

# Migration PRs add their member names here.
MIGRATION_CODES = {"SESSION_GENERATION_MISMATCH"}


def test_reserved_migration_block_is_used_only_by_migration_codes():
    taken = {c.name for c in ErrorCodes if 9090 <= c.value <= 9099}
    assert taken <= MIGRATION_CODES
