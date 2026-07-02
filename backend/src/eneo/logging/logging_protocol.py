# MIT License

from eneo.logging.logging import LoggingDetailsInDB, LoggingDetailsPublic


def from_domain(logging: LoggingDetailsInDB):
    return LoggingDetailsPublic(**logging.model_dump())
