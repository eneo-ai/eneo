from pydantic import BaseModel

from eneo.main.models import PaginatedResponse
from eneo.spaces.api.space_models import SpaceDashboard


class Dashboard(BaseModel):
    spaces: PaginatedResponse[SpaceDashboard]
