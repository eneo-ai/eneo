"""What Eneo tells a calling installation about itself.

The manifest is validated by the caller against the protocol's schema, and a
field it does not know is refused, so nothing is added here before the
protocol names it. Titles and descriptions are Swedish: an administrator of
the calling system reads them.
"""

from typing import Any

CONNECTOR_ID = "eneo"
ASSISTANTS = "eneo.assistants"
MAX_ASSISTANTS = 50

_EMPTY_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

MANIFEST: dict[str, Any] = {
    "protocol": 3,
    "id": CONNECTOR_ID,
    "kind": "passthrough",
    "source": "Eneo",
    "areas": [],
    "capabilities": [
        {
            "name": ASSISTANTS,
            "kind": "read",
            "title": "Assistenter i Eneo",
            "description": (
                "De assistenter i Eneo som personen får fråga från andra system."
            ),
            "input": _EMPTY_INPUT,
            "output": {
                "type": "object",
                "properties": {
                    "assistants": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["ref", "name"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["assistants"],
                "additionalProperties": False,
            },
            "model": False,
            "scope": {},
        }
    ],
    "scan": False,
    "delegation": {"audience": CONNECTOR_ID},
    "assistants": {"list": ASSISTANTS},
}
