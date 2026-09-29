from eneo.server.main import get_application


def test_module_handoff_and_admin_openapi_use_public_module_key():
    openapi = get_application().openapi()
    schemas = openapi["components"]["schemas"]

    ticket_request = schemas["ModuleTicketRequest"]
    assert ticket_request["required"] == ["module_key", "redirect_uri"]
    assert set(ticket_request["properties"]) == {"module_key", "redirect_uri", "state"}
    assert ticket_request["additionalProperties"] is False

    token_response = schemas["ModuleTokenResponse"]
    assert "module_key" in token_response["properties"]
    assert "module" not in token_response["properties"]
    assert "session_expires_at" in token_response["required"]

    paths = openapi["paths"]
    module_session = paths["/api/v1/module-auth/{module_key}/session/"]["get"]
    assert module_session["security"] == [
        {"OAuth2PasswordBearer": [], "APIKeyHeader": []}
    ]

    token_refresh = paths["/api/v1/module-auth/{module_key}/token/refresh/"]["post"]
    assert token_refresh["security"] == [
        {"OAuth2PasswordBearer": [], "APIKeyHeader": []}
    ]
    assert token_refresh["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ModuleTokenResponse"}
    assert module_session["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ModuleResourceSessionResponse"}

    assert not any(path.startswith("/api/v1/modules") for path in paths)
    assert "/api/v1/admin/modules/" in paths

    installation = schemas["ModuleInstallation"]
    assert "tenant_id" not in installation["properties"]
    assert set(installation["properties"]) == {
        "module_id",
        "module_key",
        "redirect_uris",
        "service_key_id",
        "configured",
    }

    install_config = schemas["ModuleInstallationConfig"]
    assert install_config["required"] == ["redirect_uris", "service_key_id"]
    assert install_config["properties"]["redirect_uris"]["minItems"] == 1
    # Required-but-nullable: an explicit null severs ticket exchange without
    # uninstalling; an omitted key is still a validation error.
    assert install_config["properties"]["service_key_id"]["anyOf"] == [
        {"type": "string", "format": "uuid"},
        {"type": "null"},
    ]

    assignment_path = paths["/api/v1/admin/modules/{module_key}/"]
    assert {"put", "delete"} == set(assignment_path)
    module_key = assignment_path["put"]["parameters"][0]
    assert module_key["name"] == "module_key"
    assert module_key["schema"]["pattern"] == "^[A-Za-z0-9][A-Za-z0-9._-]*$"
    assert module_key["schema"]["maxLength"] == 64
    assert assignment_path["put"]["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ModuleInstallationConfig"}

    response_models = {
        "put": "ModuleInstallation",
        "delete": "ModuleInstallationChange",
    }
    for method in ("put", "delete"):
        response_schema = assignment_path[method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {
            "$ref": f"#/components/schemas/{response_models[method]}"
        }
