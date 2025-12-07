from enum import Enum


class Outcome(str, Enum):
    """Indicate success or failure of audited action"""

    SUCCESS = "success"
    FAILURE = "failure"
