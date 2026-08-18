from eneo.server.main import get_application


def test_module_handoff_openapi_uses_public_key_and_keeps_admin_uuid():
    openapi = get_application().openapi()
    schemas = openapi["components"]["schemas"]

    ticket_request = schemas["ModuleTicketRequest"]
    assert ticket_request["required"] == ["module_key", "redirect_uri"]
    assert set(ticket_request["properties"]) == {"module_key", "redirect_uri", "state"}
    assert ticket_request["additionalProperties"] is False

    module_name = schemas["ModuleCreate"]["properties"]["name"]
    assert module_name["minLength"] == 1

    assignment_response = schemas["ModuleTenantAssignment"]
    assert assignment_response["required"] == [
        "tenant_id",
        "module_id",
        "module_key",
        "enabled",
        "changed",
    ]
    assert set(assignment_response["properties"]) == {
        "tenant_id",
        "module_id",
        "module_key",
        "enabled",
        "changed",
    }

    token_response = schemas["ModuleTokenResponse"]
    assert "module_key" in token_response["properties"]
    assert "module" not in token_response["properties"]

    paths = openapi["paths"]
    module_session = paths["/api/v1/module-auth/{module_key}/session/"]["get"]
    assert module_session["security"] == [
        {"OAuth2PasswordBearer": [], "APIKeyHeader": []}
    ]
    assert module_session["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ModuleResourceSessionResponse"}

    client_config_parameters = paths[
        "/api/v1/modules/{tenant_id}/{module_id}/client-config/"
    ]["patch"]["parameters"]
    module_id = next(
        parameter
        for parameter in client_config_parameters
        if parameter["name"] == "module_id"
    )
    assert module_id["schema"]["format"] == "uuid"

    assignment_path = paths["/api/v1/modules/{tenant_id}/{module_id}/"]
    assert {"put", "delete"}.issubset(assignment_path)
    for method in ("put", "delete"):
        response_schema = assignment_path[method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/ModuleTenantAssignment"
        }
