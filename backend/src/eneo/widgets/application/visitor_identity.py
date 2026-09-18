# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import hashlib
import hmac
from typing import Optional
from uuid import UUID, uuid4

from eneo.main.config import Settings, get_settings
from eneo.widgets.domain.widget import Widget


class VisitorIdentity:
    """Server-issued pseudonymous visitor ids.

    A visitor id only counts when it comes with the key the server minted for
    it, so a browser can keep its pseudonym (and the conversations owned by
    it) across visits while nobody can claim someone else's. The key is an
    HMAC over widget and visitor id with a secret derived from the
    deployment's signing key, so nothing is stored.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def _secret(self) -> bytes:
        return hashlib.sha256(
            f"eneo-widget-visitor:{self.settings.url_signing_key}".encode()
        ).digest()

    def key_for(self, widget: Widget, visitor_id: UUID) -> str:
        assert widget.id is not None
        message = f"{widget.id}:{visitor_id}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, widget: Widget, visitor_id: UUID, key: Optional[str]) -> bool:
        if not key:
            return False
        return hmac.compare_digest(self.key_for(widget, visitor_id), key)

    def resolve(
        self, widget: Widget, visitor_id: Optional[UUID], key: Optional[str]
    ) -> UUID:
        """The visitor id to mint for: the claimed one when its key verifies,
        otherwise a fresh pseudonym. A bad key never errors, it just starts over."""
        if visitor_id is not None and self.verify(widget, visitor_id, key):
            return visitor_id
        return uuid4()
