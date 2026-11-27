from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB


class IconMetadataCreate(BaseModel):
    tenant_id: UUID


class IconMetadata(InDB, IconMetadataCreate):
    pass


class IconInUseError(Exception):
    code = "icon_in_use"

    def __init__(self) -> None:
        super().__init__(
            "The icon is still shown by an assistant, app, space or group chat. "
            "Remove it there first; the icon is deleted when nothing shows it."
        )


class IconNotAttachableError(Exception):
    code = "icon_not_attachable"

    def __init__(self) -> None:
        super().__init__(
            "Only an icon you uploaded can be shown. Upload the image first."
        )
