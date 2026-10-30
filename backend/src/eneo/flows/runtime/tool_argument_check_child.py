"""Start only the schema checker from this checkout, without a server main."""

from __future__ import annotations

import sys
from multiprocessing.connection import Connection
from pathlib import Path

# The interpreter can have another checkout installed, and a server's launch
# script need not put backend/src on PYTHONPATH. The entry file owns its source.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eneo.flows.runtime.tool_argument_check import serve_tool_argument_checks

if __name__ == "__main__":
    with Connection(int(sys.argv[1])) as connection:
        serve_tool_argument_checks(connection, float(sys.argv[2]))
