from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.spaces.space_factory import SpaceFactory
from eneo.tenants.tenant import TenantInDB

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def tenant():
    return TenantInDB(
        id=uuid4(), name="tenant", quota_limit=100, created_at=NOW, updated_at=NOW
    )


def model(owner, *, output=4096, window=None):
    return CompletionModel(
        tenant=owner,
        tenant_id=owner.id,
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        nickname="model",
        name="model",
        max_input_tokens=16384,
        max_output_tokens=output,
        context_window_tokens=window,
        vision=False,
        family=None,
        hosting=None,
        org=None,
        stability=None,
        open_source=False,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=False,
        provider_id=uuid4(),
        provider_type="openai",
        litellm_model_name="openai/actual-route",
    )


class Repository:
    def __init__(self, owners, spaces=()):
        self.owners = owners
        self.spaces = spaces

    async def tenants(self, tenant_id):
        for owner in self.owners:
            if tenant_id is None or owner.id == tenant_id:
                yield owner

    async def builder_spaces(self, owner):
        for space in self.spaces:
            if space.tenant_id == owner.id:
                yield space

    async def active_provider_ids(self, owner):
        return {
            m.provider_id
            for s in self.spaces
            if s.tenant_id == owner.id
            for m in s.completion_models
        }

    async def published_flows(self, owner):
        for item in ():
            yield item

    async def runs_for_tenant(self, owner):
        for item in ():
            yield item


def space(owner, models):
    result = SpaceFactory.create_space("space", owner.id)
    result.id = uuid4()
    result.completion_models = models
    return result


@pytest.mark.asyncio
async def test_builder_reports_old_stored_values_without_claiming_verification():
    from eneo.cli.model_capacity_readiness import report_tenant

    owner = tenant()
    old = model(owner)
    other = model(owner, output=4097)
    repository = Repository([owner], [space(owner, [old, other])])

    result = await report_tenant(repository, owner)

    assert len(result["models"]) == 2
    records = {r["model_id"]: r for r in result["models"]}
    record = records[str(old.id)]
    assert record == {
        "model_id": str(old.id),
        "name": "model",
        "provider_id": str(old.provider_id),
        "provider_type": "openai",
        "route": "openai/model",
        "stored": {
            "max_input_tokens": 16384,
            "max_output_tokens": 4096,
            "context_window_tokens": None,
        },
        "uses": {"builder": {"count": 1}},
        "required_dimensions": {
            "builder": [
                "max_input_tokens",
                "max_output_tokens",
                "context_window_tokens",
            ]
        },
        "missing_dimensions": ["context_window_tokens"],
        "verification": "unverified",
    }
    assert records[str(other.id)]["verification"] == "unverified"
    assert records[str(other.id)]["stored"]["max_output_tokens"] == 4097
    assert result["summary"]["models_with_missing_dimensions"] == 2
    assert result["summary"]["models_without_missing_dimensions"] == 0
    assert {r["model_id"]: r["uses"] for r in result["summary"]["disabled_uses"]} == {
        str(old.id): ["builder"],
        str(other.id): ["builder"],
    }


def version(owner, flow_id, assistant_ids, number=1, modes=None):
    from eneo.flows.domain.flow import FlowStep, FlowVersion
    from eneo.flows.published_definition import (
        build_published_definition_json,
        published_definition_checksum,
    )

    definition = build_published_definition_json(
        flow_id=flow_id,
        name="private flow name",
        description="private content",
        metadata_json=None,
        steps=[
            dict(
                step_id=str(uuid4()),
                **FlowStep(
                    id=uuid4(),
                    assistant_id=aid,
                    step_order=i + 1,
                    input_source="flow_input" if i == 0 else "previous_step",
                    input_type="text",
                    output_type="text",
                    output_mode=modes[i] if modes else "pass_through",
                ).model_dump(mode="json"),
            )
            for i, aid in enumerate(assistant_ids)
        ],
    )
    return FlowVersion(
        flow_id=flow_id,
        tenant_id=owner.id,
        version=number,
        definition_json=definition,
        definition_checksum=published_definition_checksum(definition),
        created_at=NOW,
        updated_at=NOW,
    )


class FlowRepository(Repository):
    def __init__(self, owners, spaces=()):
        super().__init__(owners, spaces)
        self.flows = []
        self.runs = []
        self.versions = {}
        self.assistants = {}

    async def published_flows(self, owner):
        for flow in self.flows:
            if flow.tenant_id == owner.id and flow.published_version is not None:
                yield flow

    async def runs_for_tenant(self, owner):
        for run in self.runs:
            if run.tenant_id == owner.id:
                yield run

    async def get_version(self, owner, flow_id, number):
        return self.versions[owner.id, flow_id, number]

    async def assistant_model(self, owner, assistant_id):
        return self.assistants[owner.id, assistant_id]


@pytest.mark.asyncio
async def test_published_and_pinned_run_models_use_execution_dimensions_and_skip_terminal_runs():
    from eneo.cli.model_capacity_readiness import report_tenant
    from eneo.flows.domain.flow import FlowRunStatusSnapshot, FlowSparse
    from eneo.flows.enums import FlowRunStatus, is_terminal_flow_run_status

    owner = tenant()
    repository = FlowRepository([owner])
    published, pinned, unused = model(owner), model(owner, output=None), model(owner)
    pinned.max_input_tokens = None
    flow_id, aid, pinned_aid, unused_aid = [uuid4() for _ in range(4)]
    repository.assistants = {
        (owner.id, aid): published,
        (owner.id, pinned_aid): pinned,
        (owner.id, unused_aid): unused,
    }
    repository.flows = [
        FlowSparse(
            id=flow_id,
            tenant_id=owner.id,
            space_id=uuid4(),
            name="private",
            published_version=2,
        )
    ]
    repository.versions = {
        (owner.id, flow_id, 1): version(owner, flow_id, [pinned_aid]),
        (owner.id, flow_id, 2): version(
            owner,
            flow_id,
            [aid, aid, unused_aid],
            2,
            ["pass_through", "pass_through", "compose_text"],
        ),
    }
    for status in FlowRunStatus:
        run_flow = uuid4() if is_terminal_flow_run_status(status) else flow_id
        repository.runs.append(
            FlowRunStatusSnapshot(
                id=uuid4(),
                flow_id=run_flow,
                flow_version=1,
                tenant_id=owner.id,
                trace_id=uuid4(),
                status=status,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    result = await report_tenant(repository, owner)
    records = {r["model_id"]: r for r in result["models"]}
    assert set(records) == {str(published.id), str(pinned.id)}
    assert records[str(published.id)]["uses"] == {
        "published_flow": {"count": 1, "ids": [str(flow_id)]}
    }
    assert records[str(published.id)]["missing_dimensions"] == []
    assert records[str(published.id)]["required_dimensions"] == {
        "published_flow": ["max_input_tokens", "max_output_tokens"]
    }
    assert records[str(pinned.id)]["missing_dimensions"] == [
        "max_input_tokens",
        "max_output_tokens",
    ]
    active_ids = sorted(
        str(r.id) for r in repository.runs if not is_terminal_flow_run_status(r.status)
    )
    assert records[str(pinned.id)]["uses"] == {
        "resumable_run": {"count": len(active_ids), "ids": active_ids}
    }
    assert result["summary"] == {
        "models_without_missing_dimensions": 1,
        "models_with_missing_dimensions": 1,
        "disabled_uses": [{"model_id": str(pinned.id), "uses": ["resumable_run"]}],
    }


@pytest.mark.asyncio
async def test_json_tenant_filter_exit_codes_and_content_allowlist(capsys):
    import json

    from eneo.cli.model_capacity_readiness import run_report
    from eneo.flows.domain.flow import FlowRunStatusSnapshot, FlowSparse

    selected, foreign = tenant(), tenant()
    good, bad = model(selected, window=20000), model(foreign)
    repository = FlowRepository(
        [selected, foreign], [space(selected, [good]), space(foreign, [bad])]
    )
    for owner, completion in [(selected, good), (foreign, bad)]:
        fid, aid = uuid4(), uuid4()
        repository.flows.append(
            FlowSparse(
                id=fid,
                tenant_id=owner.id,
                space_id=uuid4(),
                name="private",
                published_version=1,
            )
        )
        repository.runs.append(
            FlowRunStatusSnapshot(
                id=uuid4(),
                flow_id=fid,
                flow_version=1,
                tenant_id=owner.id,
                trace_id=uuid4(),
                status="queued",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        repository.versions[owner.id, fid, 1] = version(owner, fid, [aid])
        repository.assistants[owner.id, aid] = completion
    assert (
        await run_report(repository, tenant_id=selected.id, output_format="json") == 0
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert list(payload) == ["tenants"]
    assert len(payload["tenants"]) == 1
    assert payload["tenants"][0]["tenant_id"] == str(selected.id)
    assert str(foreign.id) not in output
    assert str(bad.id) not in output
    assert str(repository.flows[1].id) not in output
    assert str(repository.runs[1].id) not in output
    assert "private" not in output
    assert payload["tenants"][0]["models"][0]["required_dimensions"][
        "published_flow"
    ] == [
        "max_input_tokens",
        "max_output_tokens",
        "context_window_tokens",
    ]
    assert await run_report(repository, tenant_id=None, output_format="json") == 1
    all_reports = json.loads(capsys.readouterr().out)["tenants"]
    assert len(all_reports) == 2
    assert all_reports[1]["summary"]["disabled_uses"] == [
        {"model_id": str(bad.id), "uses": ["builder"]}
    ]
    assert await run_report(repository, tenant_id=uuid4(), output_format="json") == 2


@pytest.mark.parametrize(
    "args", [[], ["report", "--tenant-id", "invalid"], ["report", "--format", "csv"]]
)
def test_usage_errors(args):
    from eneo.cli.model_capacity_readiness import main

    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


@pytest.mark.asyncio
async def test_database_failure_closes_and_does_not_expose_credentials(
    monkeypatch, capsys, caplog
):
    import argparse
    import logging
    import sys
    from types import ModuleType, SimpleNamespace

    from eneo.cli.model_capacity_readiness import _run_database

    class Manager:
        closed = False

        def init(self, url):
            logging.getLogger("eneo.database.database").critical("credential-sentinel")
            raise RuntimeError("credential-sentinel")

        async def close(self):
            self.closed = True

    manager = Manager()
    database = ModuleType("eneo.database.database")
    database.sessionmanager = manager
    config = ModuleType("eneo.main.config")
    config.get_settings = lambda: SimpleNamespace(database_url="credential-sentinel")
    monkeypatch.setitem(sys.modules, "eneo.database.database", database)
    monkeypatch.setitem(sys.modules, "eneo.main.config", config)
    assert await _run_database(argparse.Namespace(tenant_id=None, format="json")) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "credential-sentinel" not in output.err
    assert "credential-sentinel" not in caplog.text
    assert manager.closed


def _run_entry_point(script, *, env, cwd):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=cwd,
    )


@pytest.mark.parametrize("catalogue_setting", [None, "False", ""])
def test_entry_point_reads_no_network_before_its_database(tmp_path, catalogue_setting):
    import os

    env = {
        key: value
        for key, value in os.environ.items()
        if key != "LITELLM_LOCAL_MODEL_COST_MAP"
    }
    if catalogue_setting is not None:
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = catalogue_setting
    env.update(POSTGRES_HOST="127.0.0.1", POSTGRES_PORT="1")
    result = _run_entry_point(
        """
import socket, sys
hosts = []
real_getaddrinfo = socket.getaddrinfo
def record(host, *args, **kwargs):
    hosts.append(host)
    return real_getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = record
real_connect = socket.socket.connect
def connect(self, address):
    hosts.append(address[0] if isinstance(address, tuple) else address)
    return real_connect(self, address)
socket.socket.connect = connect
from eneo.cli.model_capacity_readiness import main
code = main(["report"])
print(sorted({str(host) for host in hosts}), file=sys.stderr)
raise SystemExit(code)
""",
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 3, result.stderr
    assert result.stdout == ""
    reached = result.stderr.strip().splitlines()[-1]
    assert "github" not in reached
    assert set(eval(reached)) <= {"127.0.0.1", "localhost"}


def test_entry_point_invalid_settings_exit_without_values(tmp_path):
    import os

    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "POSTGRES_PASSWORD": "s3cret9-sentinel",
    }
    result = _run_entry_point(
        "from eneo.cli.model_capacity_readiness import main; raise SystemExit(main(['report']))",
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 3, result.stderr
    assert result.stdout == ""
    assert "s3cret9-sentinel" not in result.stderr
    assert "capacity readiness report failed" in result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_model", ["unbound", "missing"])
async def test_completion_step_without_a_model_leaves_the_report_incomplete(
    monkeypatch, stored_model
):
    from types import SimpleNamespace

    from eneo.cli import model_capacity_readiness_repo
    from eneo.cli.model_capacity_readiness_repo import ModelCapacityReadinessRepository

    owner = tenant()
    bound = None if stored_model == "unbound" else uuid4()

    class Session:
        async def execute(self, statement):
            return SimpleNamespace(one_or_none=lambda: (bound,))

    class Models:
        def __init__(self, session, tenant):
            pass

        async def one_or_none(self, model_id):
            return None

    monkeypatch.setattr(
        model_capacity_readiness_repo, "CompletionModelRepository", Models
    )
    with pytest.raises(ValueError):
        await ModelCapacityReadinessRepository(Session()).assistant_model(
            owner, uuid4()
        )


@pytest.mark.asyncio
async def test_builder_eligibility_and_text_with_unknown_capacity(capsys):
    from eneo.cli.model_capacity_readiness import run_report

    owner = tenant()
    unknown, disabled, inactive = model(owner, output=None), model(owner), model(owner)
    unknown.max_input_tokens = None
    loaded = space(owner, [unknown, disabled, inactive])
    disabled.is_org_enabled = False

    class ActiveRepository(FlowRepository):
        async def active_provider_ids(self, owner):
            return {unknown.provider_id, disabled.provider_id}

    repository = ActiveRepository([owner], [loaded])
    assert await run_report(repository, tenant_id=None, output_format="text") == 1
    output = capsys.readouterr().out
    assert str(unknown.id) in output
    assert str(disabled.id) not in output
    assert str(inactive.id) not in output
    assert (
        'Stored: {"context_window_tokens": null, "max_input_tokens": null, "max_output_tokens": null}'
        in output
    )
    assert (
        "Missing: max_input_tokens, max_output_tokens, context_window_tokens" in output
    )
    assert "Verification: unverified" in output
    assert f"Would disable {unknown.id}: builder" in output


@pytest.mark.asyncio
async def test_incomplete_scan_emits_no_partial_report(capsys):
    from eneo.cli.model_capacity_readiness import run_report
    from eneo.flows.domain.flow import FlowSparse

    first, second = tenant(), tenant()
    repository = FlowRepository([first, second])
    fid = uuid4()
    repository.flows.append(
        FlowSparse(
            id=fid,
            tenant_id=second.id,
            space_id=uuid4(),
            name="private",
            published_version=1,
        )
    )
    broken = version(second, fid, [uuid4()])
    broken.definition_checksum = "invalid"
    repository.versions[second.id, fid, 1] = broken
    with pytest.raises(Exception):
        await run_report(repository, tenant_id=None, output_format="json")
    assert capsys.readouterr().out == ""
