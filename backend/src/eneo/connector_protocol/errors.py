"""The refusals of the connector protocol.

Every error answer has one shape, ``{"error": {"code", "message"}}``, with a
code from a short list. The message is Swedish and may be shown to the person.
A 401 always means that the calling installation's own credentials were
refused; anything about the person is a 403.
"""


class ConnectorProtocolError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    def body(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}


def installation_refused() -> ConnectorProtocolError:
    return ConnectorProtocolError(401, "denied", "Ogiltigt behörighetsbevis.")


def person_missing() -> ConnectorProtocolError:
    return ConnectorProtocolError(
        403,
        "denied",
        "Din inloggning kan inte styrkas mot Eneo i den här sessionen.",
    )


def person_refused() -> ConnectorProtocolError:
    return ConnectorProtocolError(
        403,
        "denied",
        "Eneo godkänner inte din inloggning. Be systemförvaltaren koppla ditt konto.",
    )


def denied(
    message: str = "Du har inte behörighet till det här i Eneo.",
) -> ConnectorProtocolError:
    return ConnectorProtocolError(403, "denied", message)


def invalid(message: str = "Ogiltig förfrågan.") -> ConnectorProtocolError:
    return ConnectorProtocolError(400, "invalid", message)


def not_found(message: str) -> ConnectorProtocolError:
    return ConnectorProtocolError(404, "not-found", message)


def unavailable(message: str = "Eneo svarar inte just nu.") -> ConnectorProtocolError:
    return ConnectorProtocolError(503, "unavailable", message)
