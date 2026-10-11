from enum import StrEnum


class ConversationPolicySource(StrEnum):
    OWN = "own"
    SPACE = "space"
    ORGANIZATION = "organization"
