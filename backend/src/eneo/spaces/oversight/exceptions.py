# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Refusals of the tenant-admin space oversight commands.

Registered in ``eneo.server.exception_handlers.DOMAIN_EXCEPTION_MAP`` with
their status, error code and message.
"""


class SpaceLastAdminError(Exception):
    """The change would take a space from at least one manageable
    administrator to none."""


class SpaceAlreadyMemberError(Exception):
    """The user or group already has a direct row in the space."""


class SpaceSelfAccessError(Exception):
    """An administrator targeted their own access outside join and leave."""


class SpaceAdminMustJoinError(Exception):
    """Another tenant administrator would be given content access, or more
    of it, without joining: they join themselves, with a reason."""
