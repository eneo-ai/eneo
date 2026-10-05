import pytest


def test_existing_default_and_beta_callback_coexist(test_settings):
    settings = test_settings.model_copy(
        update={
            "oauth_callback_url": "https://app.example/integrations/callback/token/",
            "oauth_callback_urls": [
                "https://beta.example/integrations/callback/token/"
            ],
        }
    )
    assert settings.integration_callback_uri() == settings.oauth_callback_url
    assert (
        settings.integration_callback_uri(settings.oauth_callback_urls[0])
        == settings.oauth_callback_urls[0]
    )


def test_public_origin_retains_the_existing_callback_fallback(test_settings):
    settings = test_settings.model_copy(
        update={"oauth_callback_url": None, "public_origin": "https://app.example"}
    )
    assert (
        settings.integration_callback_uri()
        == "https://app.example/integrations/callback/token/"
    )


@pytest.mark.parametrize(
    "callback",
    [
        "http://external.example/callback",
        "https://user:password@beta.example/callback",
        "https://beta.example/callback?other=1",
        "https://beta.example/callback#fragment",
        " https://beta.example/callback",
        "https://beta.example/call\nback",
    ],
)
def test_even_operator_registered_callbacks_must_be_safe(test_settings, callback):
    settings = test_settings.model_copy(update={"oauth_callback_urls": [callback]})
    with pytest.raises(ValueError):
        settings.integration_callback_uri(callback)
