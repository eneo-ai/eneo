from enum import StrEnum


class ConversationPolicySource(StrEnum):
    # The Assistant's or App's own retention period, set on the conversation's owner.
    ASSISTANT_OR_APP = "assistant_or_app"
    SPACE = "space"
    ORGANIZATION = "organization"
