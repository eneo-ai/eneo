# MIT License

from typing import Optional

from pydantic import BaseModel, ConfigDict, Json

from intric.main.models import InDB


class LoggingDetails(BaseModel):
    context: Optional[str] = None
    model_kwargs: dict[str, object]
    json_body: Optional[str] = None

    model_config = ConfigDict(protected_namespaces=())


class LoggingDetailsInDB(LoggingDetails, InDB):
    pass


class LoggingDetailsPublic(LoggingDetails):
    json_body: Json[object]  # type: ignore[assignment]  # intentionally widens Optional[str] from parent to Json[object] for parsed JSON response
