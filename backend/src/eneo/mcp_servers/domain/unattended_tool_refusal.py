"""The level that refuses an unattended caller's tool.

``unattended_tool_use`` decides the value. The enum has a module of its own
that imports nothing of Eneo: a flow run's stored error names the refusing
level, and the decision's module cannot be imported there, because it imports
the database tables and the flow tables import the flow run's models.
"""

from enum import StrEnum


class UnattendedToolRefusal(StrEnum):
    """What refuses a tool for a caller that runs with nobody watching: a
    personal space, or else the first level that says no, in the order
    instance server, instance tool, space."""

    # The instance admin's server.
    SERVER_NOT_FOUND = "server_not_found"
    SERVER_DISABLED = "server_disabled"
    # A capability provider or one of Eneo's own servers: reached through its
    # capability, never as a tool somebody picked.
    SERVER_NOT_GENERAL = "server_not_general"
    # The server answers as the acting user; an unattended caller has none
    # whose rights the answer may carry.
    SERVER_FORWARDS_IDENTITY = "server_forwards_identity"
    # The server takes an admin-supplied credential and its registered
    # address is plain http to any host other than localhost, 127.0.0.1 or
    # ::1: the call would send the credential readable on the network path.
    SERVER_CREDENTIAL_NEEDS_HTTPS = "server_credential_needs_https"
    # The instance admin's tool.
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_REMOVED_AT_SERVER = "tool_removed_at_server"
    # New, or changed at the server, and no admin has looked at it yet. The
    # call goes to the server as it is now, so the approved definition says
    # nothing about what would answer.
    TOOL_WAITING_FOR_REVIEW = "tool_waiting_for_review"
    TOOL_SWITCHED_OFF = "tool_switched_off"
    # The space.
    SPACE_IS_PERSONAL = "space_is_personal"
    SERVER_NOT_IN_SPACE = "server_not_in_space"
    TOOL_SWITCHED_OFF_IN_SPACE = "tool_switched_off_in_space"
    SERVER_BELOW_SPACE_CLASSIFICATION = "server_below_space_classification"
