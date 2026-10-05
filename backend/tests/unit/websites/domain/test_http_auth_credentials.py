from typing import cast
from uuid import uuid4

import pytest

from eneo.embedding_models.domain.embedding_model import EmbeddingModel
from eneo.websites.domain.crawl_run import CrawlType
from eneo.websites.domain.http_auth_credentials import (
    HttpAuthCredentials,
    HttpAuthDestinationError,
)
from eneo.websites.domain.website import UpdateInterval, Website
from eneo.websites.presentation.website_models import WebsiteUpdate


@pytest.fixture
def website() -> Website:
    website = Website(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        space_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        url="https://intranet.example/docs",
        name="Municipal guidance",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        embedding_model=cast(EmbeddingModel, object()),
        size=0,
        latest_crawl=None,
    )
    return website.set_http_auth("employee", "stored-secret")


@pytest.mark.parametrize(
    "url",
    [
        "https://intranet.example/other?revision=2",
        "HTTPS://INTRANET.EXAMPLE:443/other",
    ],
)
def test_same_origin_update_retains_credentials(website: Website, url: str) -> None:
    credentials = website.http_auth
    website.update(url=url)
    assert website.url == url
    assert website.http_auth is credentials


@pytest.mark.parametrize(
    "url",
    [
        "https://collector.example/docs",
        "https://intranet.example:8443/docs",
        "http://intranet.example/docs",
    ],
)
def test_origin_change_requires_explicit_auth_update(
    website: Website, url: str
) -> None:
    credentials = website.http_auth
    with pytest.raises(HttpAuthDestinationError, match="Re-enter"):
        website.update(url=url)
    assert website.url == "https://intranet.example/docs"
    assert website.http_auth is credentials


def test_origin_change_can_explicitly_remove_auth(website: Website) -> None:
    website.update(
        url="https://collector.example/",
        http_auth_username=None,
        http_auth_password=None,
    )
    assert website.url == "https://collector.example/"
    assert website.http_auth is None


def test_new_credentials_bind_to_new_origin(website: Website) -> None:
    website.update(
        url="http://intranet.example:8080/",
        http_auth_username="replacement",
        http_auth_password="new-secret",
    )
    assert website.http_auth is not None
    assert website.http_auth.username == "replacement"
    assert website.http_auth.password == "new-secret"
    assert website.http_auth.auth_domain == "http://intranet.example:8080"
    HttpAuthCredentials.require_destination(
        website.http_auth.auth_domain, "http://intranet.example:8080/next"
    )


def test_scheme_upgrade_also_requires_explicit_credentials(website: Website) -> None:
    website.url = "http://intranet.example/docs"
    website.set_http_auth("employee", "http-secret")
    with pytest.raises(HttpAuthDestinationError):
        website.update(url="https://intranet.example/docs")
    assert website.http_auth is not None
    assert website.http_auth.auth_domain == "http://intranet.example"


def test_idna2008_distinct_hostname_cannot_retain_credentials(website: Website) -> None:
    website.url = "https://fass.example/docs"
    website.set_http_auth("employee", "stored-secret")
    with pytest.raises(HttpAuthDestinationError):
        website.update(url="https://faß.example/docs")
    assert website.url == "https://fass.example/docs"


def test_unicode_credentials_use_crawler_transport_hostname() -> None:
    credentials = HttpAuthCredentials.from_website_url(
        "employee", "new-secret", "https://faß.example/docs"
    )
    assert credentials.auth_domain == "https://xn--fa-hia.example"


@pytest.mark.parametrize(
    ("binding", "url"),
    [
        ("https://example.com", "HTTPS://EXAMPLE.COM:443/docs"),
        ("http://example.com", "http://example.com:80/docs"),
        ("https://[2001:db8::1]", "https://[2001:db8::1]:443/docs"),
        ("https://[2001:db8::1]", "https://[2001:0db8:0:0:0:0:0:1]/docs"),
        ("https://xn--rksmrgs-5wao1o.example", "https://räksmörgås.example/docs"),
        ("https://xn--fa-hia.example", "https://faß.example/docs"),
        ("example.com:443", "https://example.com/docs"),
    ],
)
def test_destination_accepts_normalized_origin(binding: str, url: str) -> None:
    HttpAuthCredentials.require_destination(binding, url)


@pytest.mark.parametrize(
    ("binding", "url"),
    [
        (None, "https://example.com/docs"),
        ("example.com", "http://example.com/docs"),
        ("https://example.com", "http://example.com/docs"),
        ("http://example.com", "https://example.com/docs"),
        ("example.com", "https://other.example/docs"),
        ("example.com:8443", "https://example.com/docs"),
        ("https://example.com", "https://example.com:8443/docs"),
        ("https://example.com/path", "https://example.com/docs"),
        ("https://[broken", "https://example.com/docs"),
        ("https://fass.example", "https://faß.example/docs"),
    ],
)
def test_destination_rejects_unproven_or_different_origin(
    binding: str | None, url: str
) -> None:
    with pytest.raises(HttpAuthDestinationError):
        HttpAuthCredentials.require_destination(binding, url)


def test_legacy_https_path_update_does_not_rebind_secret(website: Website) -> None:
    website.http_auth = HttpAuthCredentials(
        username="employee", password="stored-secret", auth_domain="intranet.example"
    )
    website.update(url="https://intranet.example/other")
    assert website.http_auth.auth_domain == "intranet.example"


def test_legacy_http_site_can_pause_schedule_and_edit_metadata_from_ui(
    website: Website,
) -> None:
    website.url = "http://intranet.example/docs"
    website.update_interval = UpdateInterval.DAILY
    website.http_auth = HttpAuthCredentials(
        username="employee", password="stored-secret", auth_domain="intranet.example"
    )
    credentials = website.http_auth
    # WebsiteEditor sends the unchanged URL and all metadata on every save,
    # omitting auth fields when the user keeps the saved password.
    update = WebsiteUpdate(
        url=website.url,
        name="Renamed municipal guidance",
        crawl_type=CrawlType.SITEMAP,
        update_interval=UpdateInterval.NEVER,
        download_files=True,
    )

    website.update(
        url=update.url,
        name=update.name,
        crawl_type=update.crawl_type,
        update_interval=update.update_interval,
        download_files=update.download_files,
        http_auth_username=update.http_auth_username,
        http_auth_password=update.http_auth_password,
    )

    assert website.url == "http://intranet.example/docs"
    assert website.name == "Renamed municipal guidance"
    assert website.update_interval is UpdateInterval.NEVER
    assert website.crawl_type is CrawlType.SITEMAP
    assert website.download_files is True
    assert website.http_auth is credentials
    with pytest.raises(HttpAuthDestinationError):
        HttpAuthCredentials.require_destination(credentials.auth_domain, website.url)


def test_inconsistent_stored_binding_requires_credentials_again(
    website: Website,
) -> None:
    website.http_auth = HttpAuthCredentials(
        username="employee", password="stored-secret", auth_domain="other.example"
    )
    with pytest.raises(HttpAuthDestinationError):
        website.update(url="https://intranet.example/other")
