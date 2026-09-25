from enum import Enum
from typing import Literal

from eneo.integration.presentation.models import (
    BaseListModel,
    IntegrationPreviewData,
    SharePointTreeResponse,
)


class SharePointFixtureScenario(str, Enum):
    REPRESENTATIVE = "representative"
    LARGE_TENANT = "large_tenant"
    EMPTY = "empty"


class SharePointFixturePreviewResponse(BaseListModel[IntegrationPreviewData]):
    fixture: Literal[True] = True
    scenario: SharePointFixtureScenario


class SharePointFixtureTreeResponse(SharePointTreeResponse):
    fixture: Literal[True] = True
    scenario: SharePointFixtureScenario
