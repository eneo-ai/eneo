from types import SimpleNamespace
from uuid import uuid4

from eneo.apps.app_runs.api.app_run_assembler import AppRunAssembler
from eneo.apps.app_runs.app_run import AppRun
from eneo.apps.app_runs.app_run_factory import AppRunFactory
from eneo.apps.app_runs.app_run_repo import _serialize_skill_provenance
from eneo.skills.domain.skill import SkillExecutionReference
from eneo.users.user import UserSparse
from tests.fixtures import TEST_USER


def _reference() -> SkillExecutionReference:
    return SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=3,
        content_digest="a" * 64,
        position=1,
    )


def _database_row(skill_provenance):
    return SimpleNamespace(
        created_at=None,
        updated_at=None,
        id=uuid4(),
        job_id=None,
        app_id=uuid4(),
        user_id=TEST_USER.id,
        tenant_id=TEST_USER.tenant_id,
        input_files=[],
        input_text="input",
        output_text=None,
        user=TEST_USER,
        num_tokens_input=None,
        num_tokens_output=None,
        skill_provenance=skill_provenance,
        job=None,
        completion_model_id=uuid4(),
    )


def test_app_run_factory_validates_persisted_provenance_into_domain_type():
    reference = _reference()

    app_run = AppRunFactory().create_app_run_from_db(
        _database_row(_serialize_skill_provenance((reference,)))
    )

    assert app_run.skill_provenance == (reference,)


def test_app_run_factory_preserves_legacy_null_snapshot():
    app_run = AppRunFactory().create_app_run_from_db(_database_row(None))

    assert app_run.skill_provenance is None


def test_app_run_serializer_distinguishes_legacy_null_from_pinned_zero_skills():
    assert _serialize_skill_provenance(None) is None
    assert _serialize_skill_provenance(()) == []


def test_app_run_public_model_exposes_only_revision_provenance():
    reference = _reference()
    app_run = AppRun(
        created_at=None,
        updated_at=None,
        id=uuid4(),
        job_id=None,
        app_id=uuid4(),
        user_id=TEST_USER.id,
        tenant_id=TEST_USER.tenant_id,
        input_files=[],
        input_text="input",
        output=None,
        user=UserSparse.model_validate(TEST_USER),
        num_tokens_input=None,
        num_tokens_output=None,
        skill_provenance=(reference,),
        job=None,
        completion_model_id=uuid4(),
    )

    public = AppRunAssembler().from_app_run_to_model(app_run)

    assert public.skill_provenance == [reference]
    assert set(public.model_dump()["skill_provenance"][0]) == {
        "skill_id",
        "skill_revision_id",
        "revision_number",
        "content_digest",
        "position",
    }
