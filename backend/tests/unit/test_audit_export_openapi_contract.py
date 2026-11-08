from eneo.server.main import get_application


def test_signed_audit_export_declares_streamed_file_media():
    operation = get_application().openapi()["paths"][
        "/api/v1/audit/logs/export/{job_id}/signed-download"
    ]["get"]
    content = operation["responses"]["200"]["content"]
    assert set(content) == {"text/csv", "application/x-ndjson"}
    for media in content.values():
        assert media["schema"] == {"type": "string", "format": "binary"}
