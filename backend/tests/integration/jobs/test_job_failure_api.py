from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_models import Task
from eneo.main.models import Status

pytestmark = pytest.mark.integration


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container(user=admin_user) as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def test_job_apis_mask_legacy_knowledge_prose_and_preserve_other_results(
    client,
    db_container,
    admin_user,
    admin_token: str,
) -> None:
    now = datetime.now(timezone.utc)
    failed_knowledge_id = uuid4()
    complete_knowledge_id = uuid4()
    failed_crawl_id = uuid4()
    async with db_container(user=admin_user) as container:
        container.session().add_all(
            [
                Jobs(
                    id=failed_knowledge_id,
                    user_id=admin_user.id,
                    name="legacy.pdf",
                    task=Task.UPLOAD_FILE.value,
                    status=Status.FAILED.value,
                    result_location="password=secret database host",
                    failure_code="future_failure_code",
                    finished_at=now,
                ),
                Jobs(
                    id=complete_knowledge_id,
                    user_id=admin_user.id,
                    name="complete.pdf",
                    task=Task.UPLOAD_FILE.value,
                    status=Status.COMPLETE.value,
                    result_location="/api/v1/info-blobs/123/",
                    finished_at=now,
                ),
                Jobs(
                    id=failed_crawl_id,
                    user_id=admin_user.id,
                    name="intranet.example",
                    task=Task.CRAWL.value,
                    status=Status.FAILED.value,
                    result_location="The crawl exceeded its configured time limit",
                    finished_at=now,
                ),
            ]
        )

    headers = {"Authorization": f"Bearer {admin_token}"}
    response = await client.get("/api/v1/jobs/", headers=headers)
    assert response.status_code == 200, response.text
    jobs = {item["id"]: item for item in response.json()["items"]}

    failed_knowledge = jobs[str(failed_knowledge_id)]
    assert failed_knowledge["result_location"] is None
    assert failed_knowledge["failure_code"] is None
    assert jobs[str(complete_knowledge_id)]["result_location"] == (
        "/api/v1/info-blobs/123/"
    )
    assert jobs[str(failed_crawl_id)]["result_location"] == (
        "The crawl exceeded its configured time limit"
    )

    response = await client.get(
        f"/api/v1/jobs/{failed_knowledge_id}/",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["result_location"] is None
    assert response.json()["failure_code"] is None
