# Partial stub: asyncpg ships no type information and pyright runs strict.
# Only the error hierarchy the application catches is declared here; extend
# it when application code needs more of the package.
from . import exceptions as exceptions
from .exceptions import InterfaceError as InterfaceError
from .exceptions import PostgresError as PostgresError
