"""The type that reads the address an administrator registers for a server."""

from pydantic import AnyHttpUrl

# The admin API reads a server's address with this type and stores its text.
# The client asks the same type before its redirect message names an address
# to register instead.
MCPServerAddress = AnyHttpUrl
