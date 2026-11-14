"""A calling installation a tenant trusts, and the models of its admin API."""

from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from eneo.authentication.oidc import outbound
from eneo.main.models import InDB

KEYS_PATH = "/api/connectors/jwks"


def _base_url(value: str) -> str:
    """An address the installation's keys can be fetched from.

    Held to the rules of every other request for another party's keys: https
    (or this machine, in development), a host, no user. Nothing is fetched
    here; a wrong address shows as refused calls.
    """
    url = value.strip().rstrip("/")
    try:
        outbound.check_url(url + KEYS_PATH)
    except outbound.OidcFetchError as exc:
        raise ValueError(f"The address cannot be used: {exc.reason}") from exc
    if "?" in url or "#" in url:
        raise ValueError("The address must not carry a query or a fragment")
    return url


class ConnectorInstallation(InDB):
    """An installation as stored. The shared key is not part of it."""

    tenant_id: UUID
    name: str
    base_url: str
    key_digest: str


class ConnectorInstallationPublic(InDB):
    name: str
    base_url: str = Field(
        description=(
            "The installation's own address. Its public signing keys are read "
            f"from `{KEYS_PATH}` under it."
        )
    )


class ConnectorInstallationCreate(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ] = Field(description="What administrators call the installation.")
    base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=1900), AfterValidator(_base_url)
    ] = Field(
        description=(
            "The installation's own address, for example `https://start.example`. "
            "Must use https."
        )
    )


class ConnectorInstallationCreated(ConnectorInstallationPublic):
    key: str = Field(
        description=(
            "The shared key to enter in the installation, beside Eneo's connector "
            "address. Shown this once: Eneo keeps only a digest of it."
        )
    )
