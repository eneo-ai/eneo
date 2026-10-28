def expected_set_cookie(
    name: str, value: str, max_age: int, *, production: bool
) -> str:
    """The one spelling of the browser-session cookie attributes in tests.

    Written out here, independent of ``eneo.authentication.browser_session``,
    so a test comparing against it does not check the code against itself.
    """
    return f"{name}={value}; HttpOnly; Max-Age={max_age}; Path=/; SameSite=lax" + (
        "; Secure" if production else ""
    )
