from __future__ import annotations

from io import BytesIO
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from PIL import Image


def _opaque_png(*, width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(24, 95, 180)).save(
        buffer,
        format="PNG",
    )
    return buffer.getvalue()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_metadata_routes_preserve_persisted_transcription(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("meeting.mp3", b"audio", "audio/mpeg")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    file_id = UUID(upload.json()["id"])

    async with db_container() as container:
        saved = await container.file_service().save_transcription(
            file_id,
            "durable transcript",
        )
        assert saved == "durable transcript"

    single = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
    listing = await client.get("/api/v1/files/", headers=headers)

    assert single.status_code == 200, single.text
    assert listing.status_code == 200, listing.text
    assert single.json()["transcription"] == "durable transcript"
    listed = next(
        item for item in listing.json()["items"] if item["id"] == str(file_id)
    )
    assert listed["transcription"] == "durable transcript"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_image_metadata_matches_the_selected_download_representation(
    client,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    source = _opaque_png(width=2049, height=16)
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("wide.png", source, "image/png")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()
    file_id = uploaded["id"]

    single = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
    listing = await client.get("/api/v1/files/", headers=headers)
    signed = await client.post(
        f"/api/v1/files/{file_id}/signed-url/",
        json={"content_disposition": "attachment"},
        headers=headers,
    )

    assert single.status_code == 200, single.text
    assert listing.status_code == 200, listing.text
    assert signed.status_code == 200, signed.text
    listed = next(item for item in listing.json()["items"] if item["id"] == file_id)
    download_url = signed.json()["url"]
    download = await client.get(
        f"{urlsplit(download_url).path}?{urlsplit(download_url).query}"
    )
    assert download.status_code == 200, download.text

    for metadata in (uploaded, single.json(), listed):
        assert metadata["mimetype"] == "image/jpeg"
        assert metadata["size"] == len(download.content)
    assert download.headers["content-type"] == "image/jpeg"
    assert int(download.headers["content-length"]) == len(download.content)
