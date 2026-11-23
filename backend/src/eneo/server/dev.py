"""Entry point for `uv run start`, the local development server.

`uvicorn.run(..., reload=True)` imports the application in the reloader
process before it starts watching files, so a process that only watches
`src/` holds a second copy of Eneo (about 400 MB). Starting the reload
supervisor directly leaves the import to the child that serves requests.

Kept apart from `eneo.server.main` so that importing this module does not
load the application either.
"""

import uvicorn
from uvicorn.supervisors import ChangeReload


def start() -> None:
    config = uvicorn.Config(
        "eneo.server.main:app",
        host="0.0.0.0",
        port=8123,
        reload=True,
        reload_dirs="./src/",
        # Export .env to the server process before it imports Eneo, which
        # reads some settings, such as LOGLEVEL, from os.environ at import.
        # Importing the app in this process used to do that as a side effect.
        env_file=".env",
    )
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    try:
        ChangeReload(config, target=server.run, sockets=[sock]).run()
    except KeyboardInterrupt:
        pass
