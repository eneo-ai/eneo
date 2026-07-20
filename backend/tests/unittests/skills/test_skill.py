from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.skills import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    ResolvedSkillBinding,
    compose_skill_instructions,
    create_content_digest,
    normalize_skill_content,
    validate_skill_slug,
)
from eneo.skills.application.skill_service import SkillService
from eneo.skills.domain.skill import (
    NormalizedSkillContent,
    Skill,
    SkillBindingReference,
    SkillExecutionReference,
    SkillPublicationState,
    SkillRevision,
)


def _binding(*, position: int, name: str = "Payroll") -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug=name.lower(),
        revision_number=1,
        current_revision_number=1,
        display_name=name,
        instructions=f"Instructions for {name}",
        content_digest="a" * 64,
        position=position,
    )


def _service(repo: AsyncMock) -> SkillService:
    return SkillService(
        user=MagicMock(),
        repo=repo,
        space_service=AsyncMock(),
        actor_manager=MagicMock(),
    )


def _reference(
    binding: ResolvedSkillBinding, *, position: int | None = None
) -> SkillExecutionReference:
    return SkillExecutionReference(
        skill_id=binding.skill_id,
        skill_revision_id=binding.skill_revision_id,
        revision_number=binding.revision_number,
        content_digest=binding.content_digest,
        position=binding.position if position is None else position,
    )


def _skill(
    *,
    current_revision_number: int = 1,
    published_revision_number: int | None = None,
    first_published_at: datetime | None = None,
) -> Skill:
    skill_id = uuid4()
    now = datetime.now(timezone.utc)
    revision = SkillRevision(
        id=uuid4(),
        skill_id=skill_id,
        revision_number=current_revision_number,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the payroll handbook.",
        content_digest="a" * 64,
        created_by_user_id=uuid4(),
        created_at=now,
    )
    return Skill(
        id=skill_id,
        space_id=uuid4(),
        slug="payroll",
        is_active=True,
        current_revision_number=current_revision_number,
        published_revision_number=published_revision_number,
        first_published_at=first_published_at,
        created_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
        current_revision=revision,
    )


@pytest.mark.parametrize(
    "slug",
    ["payroll", "payroll-questions", "skill-2", "2fa-guidance"],
)
def test_validate_skill_slug_accepts_agent_skills_name_grammar(slug: str):
    assert validate_skill_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    ["", "Payroll", "pay_roll", "-payroll", "payroll-", "payroll--questions"],
)
def test_validate_skill_slug_rejects_invalid_values(slug: str):
    with pytest.raises(BadRequestException):
        validate_skill_slug(slug)


def test_normalize_skill_content_preserves_markdown_and_normalizes_newlines():
    assert normalize_skill_content(
        display_name="  Payroll  ",
        description="  Answers payroll questions  ",
        instructions="  # Rules\r\n\r\nUse the handbook.  ",
    ) == (
        "Payroll",
        "Answers payroll questions",
        "# Rules\n\nUse the handbook.",
    )


def test_normalized_skill_content_keeps_validation_and_digest_together():
    content = NormalizedSkillContent.create(
        display_name=" Payroll ",
        description=" Approved payroll guidance ",
        instructions=" First step\r\nSecond step ",
    )

    assert content.display_name == "Payroll"
    assert content.description == "Approved payroll guidance"
    assert content.instructions == "First step\nSecond step"
    assert content.content_digest == create_content_digest(
        display_name=content.display_name,
        description=content.description,
        instructions=content.instructions,
    )


def test_normalize_skill_content_enforces_specification_description_bound():
    with pytest.raises(BadRequestException):
        normalize_skill_content(
            display_name="Payroll",
            description="x" * (MAX_SKILL_DESCRIPTION_LENGTH + 1),
            instructions="instructions",
        )


def test_normalize_skill_content_does_not_apply_arbitrary_line_or_character_caps():
    instructions = "\n".join(["A focused instruction."] * 600)
    _, _, normalized = normalize_skill_content(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions=instructions,
    )
    assert normalized == instructions


def test_content_digest_is_stable_and_covers_all_revision_content():
    digest = create_content_digest(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the handbook.",
    )
    assert digest == create_content_digest(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the handbook.",
    )
    assert digest != create_content_digest(
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the current handbook.",
    )


@pytest.mark.parametrize(
    ("skill", "expected"),
    [
        (_skill(), SkillPublicationState.DRAFT),
        (
            _skill(
                published_revision_number=1,
                first_published_at=datetime.now(timezone.utc),
            ),
            SkillPublicationState.PUBLISHED,
        ),
        (
            _skill(
                current_revision_number=2,
                published_revision_number=1,
                first_published_at=datetime.now(timezone.utc),
            ),
            SkillPublicationState.UPDATE_PENDING,
        ),
        (
            _skill(first_published_at=datetime.now(timezone.utc)),
            SkillPublicationState.UNPUBLISHED,
        ),
    ],
)
def test_publication_state_is_derived_from_exact_revision_pointer(
    skill: Skill, expected: SkillPublicationState
):
    assert skill.publication_state is expected


def test_zero_skills_returns_base_prompt_byte_for_byte():
    base = "  Base instructions\n"
    composition = compose_skill_instructions(base_instructions=base, bindings=[])
    assert composition.prompt == base
    assert composition.provenance == ()


def test_composition_orders_skills_and_builds_matching_provenance():
    second = _binding(position=1, name="Absence")
    first = _binding(position=0, name="Payroll")

    composition = compose_skill_instructions(
        base_instructions="Base instructions", bindings=[second, first]
    )

    assert composition.prompt.startswith("Base instructions\n\n")
    assert composition.prompt.index("### Skill: Payroll") < composition.prompt.index(
        "### Skill: Absence"
    )
    assert [reference.skill_id for reference in composition.provenance] == [
        first.skill_id,
        second.skill_id,
    ]
    assert "Instructions for Payroll" not in repr(composition.provenance)


def test_composition_rejects_duplicate_positions():
    with pytest.raises(BadRequestException, match="positions must be unique"):
        compose_skill_instructions(
            base_instructions="Base",
            bindings=[_binding(position=0), _binding(position=0, name="Absence")],
        )


def test_composition_rejects_duplicate_skill_identity():
    binding = _binding(position=0)
    duplicate = ResolvedSkillBinding(
        skill_id=binding.skill_id,
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=binding.skill_space_id,
        slug="payroll",
        revision_number=2,
        current_revision_number=2,
        display_name="Payroll",
        instructions="Updated instructions",
        content_digest="b" * 64,
        position=1,
    )
    with pytest.raises(BadRequestException, match="only be bound once"):
        compose_skill_instructions(
            base_instructions="Base", bindings=[binding, duplicate]
        )


async def test_execution_snapshot_with_no_skills_preserves_base_without_repo_read():
    repo = AsyncMock()

    composition = await _service(repo).compose_for_execution_snapshot(
        tenant_id=uuid4(),
        space_id=uuid4(),
        provenance=(),
        base_instructions="  Base instructions\n",
    )

    assert composition.prompt == "  Base instructions\n"
    assert composition.provenance == ()
    repo.resolve_references_for_execution_snapshot.assert_not_awaited()


async def test_execution_snapshot_uses_persisted_order_and_allows_inactive_skill():
    payroll = replace(_binding(position=0, name="Payroll"), is_active=False)
    absence = _binding(position=1, name="Absence")
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = [payroll, absence]
    tenant_id = uuid4()
    space_id = uuid4()

    composition = await _service(repo).compose_for_execution_snapshot(
        tenant_id=tenant_id,
        space_id=space_id,
        provenance=(
            _reference(absence, position=20),
            _reference(payroll, position=10),
        ),
        base_instructions="Base",
    )

    repo.resolve_references_for_execution_snapshot.assert_awaited_once_with(
        tenant_id=tenant_id,
        parent_space_id=space_id,
        references=[
            SkillBindingReference(
                skill_id=payroll.skill_id,
                skill_revision_id=payroll.skill_revision_id,
            ),
            SkillBindingReference(
                skill_id=absence.skill_id,
                skill_revision_id=absence.skill_revision_id,
            ),
        ],
    )
    assert composition.prompt.index("### Skill: Payroll") < composition.prompt.index(
        "### Skill: Absence"
    )
    assert [reference.position for reference in composition.provenance] == [10, 20]


@pytest.mark.parametrize("field", ["revision_number", "content_digest"])
async def test_execution_snapshot_rejects_changed_revision_metadata(field: str):
    binding = _binding(position=0)
    reference = _reference(binding)
    replacement = 2 if field == "revision_number" else "b" * 64
    reference = replace(reference, **{field: replacement})
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = [binding]

    with pytest.raises(BadRequestException, match="metadata no longer matches"):
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=uuid4(),
            space_id=uuid4(),
            provenance=(reference,),
            base_instructions="Base",
        )


async def test_execution_snapshot_rejects_missing_revision():
    binding = _binding(position=0)
    repo = AsyncMock()
    repo.resolve_references_for_execution_snapshot.return_value = []

    with pytest.raises(BadRequestException, match="no longer available"):
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=uuid4(),
            space_id=uuid4(),
            provenance=(_reference(binding),),
            base_instructions="Base",
        )


@pytest.mark.parametrize("invalid", ["duplicate_position", "duplicate_skill"])
async def test_execution_snapshot_rejects_invalid_persisted_order(invalid: str):
    first = _binding(position=0, name="Payroll")
    second = _binding(position=1, name="Absence")
    if invalid == "duplicate_position":
        provenance = (_reference(first), _reference(second, position=0))
    else:
        provenance = (
            _reference(first),
            replace(
                _reference(second),
                skill_id=first.skill_id,
            ),
        )
    repo = AsyncMock()

    with pytest.raises(BadRequestException):
        await _service(repo).compose_for_execution_snapshot(
            tenant_id=uuid4(),
            space_id=uuid4(),
            provenance=provenance,
            base_instructions="Base",
        )
    repo.resolve_references_for_execution_snapshot.assert_not_awaited()
