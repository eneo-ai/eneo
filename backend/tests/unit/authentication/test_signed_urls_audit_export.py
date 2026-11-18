"""Audit downloads grant one short-lived export capability, never a session."""

import time
from uuid import uuid4

import pytest

from eneo.authentication import signed_urls
from eneo.files.file_models import ContentDisposition


def test_export_token_is_bound_to_tenant_job_and_audience():
    job_id, tenant_id = uuid4(), uuid4()
    now = int(time.time())
    token = signed_urls.generate_audit_export_download_token(
        job_id, now + 60, tenant_id, issued_at=now
    )
    payload = signed_urls.verify_audit_export_download_token(token)
    assert payload is not None
    assert payload["job_id"] == str(job_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["expires_at"] - payload["issued_at"] == 60
    assert signed_urls.verify_file_original_download_token(token) is None
    file_token = signed_urls.generate_file_original_download_token(
        job_id, now + 60, ContentDisposition.ATTACHMENT, tenant_id
    )
    assert signed_urls.verify_audit_export_download_token(file_token) is None


def test_export_token_rejects_expiry_tamper_and_excess_lifetime():
    job_id, tenant_id = uuid4(), uuid4()
    now = int(time.time())
    expired = signed_urls.generate_audit_export_download_token(
        job_id, now - 1, tenant_id, issued_at=now - 61
    )
    assert signed_urls.verify_audit_export_download_token(expired) is None
    token = signed_urls.generate_audit_export_download_token(
        job_id, now + 60, tenant_id
    )
    message, signature = token.split(".")
    assert (
        signed_urls.verify_audit_export_download_token(message[:-2] + "xx." + signature)
        is None
    )
    with pytest.raises(ValueError, match="may not live longer"):
        signed_urls.generate_audit_export_download_token(
            job_id, now + 61, tenant_id, issued_at=now
        )
