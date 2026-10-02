"""Allow the charts function in space, assistant and governance settings.

Additive only: leave existing servers, associations and role grants unchanged.
Administrators opt existing roles into Charts and add/activate its provider.

Revision ID: 202610011200
Revises: 202610011000
"""

from alembic import op

revision = "202610011200"
down_revision = "202610011000"
branch_labels = None
depends_on = None

_CONSTRAINTS = (
    ("space_capabilities", "ck_space_capability_purpose"),
    ("assistant_capabilities", "ck_assistant_capability_purpose"),
    ("governance_policy_capabilities", "ck_policy_capability_purpose"),
)
_PREVIOUS = ("web_search", "image_generation", "file_analysis", "file_creation")


def _replace_constraints(purposes: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{purpose}'" for purpose in purposes)
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"purpose IN ({allowed})")


def upgrade() -> None:
    _replace_constraints((*_PREVIOUS, "charts"))


def downgrade() -> None:
    # PostgreSQL rejects this if chart settings still exist. Never delete them
    # merely to make an older constraint fit.
    _replace_constraints(_PREVIOUS)
