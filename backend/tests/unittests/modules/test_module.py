import pytest
from pydantic import ValidationError

from eneo.modules.module import ModuleBase, ModuleCreate, ModuleInDB, Modules


@pytest.mark.parametrize("module_key", ["", " ", "\t", "\n"])
def test_module_key_rejects_empty_or_blank_values(module_key: str) -> None:
    with pytest.raises(ValidationError):
        ModuleCreate(name=module_key)


@pytest.mark.parametrize("module_key", [" tal-till-text", "tal-till-text "])
def test_module_key_rejects_leading_or_trailing_whitespace(module_key: str) -> None:
    with pytest.raises(ValidationError):
        ModuleCreate(name=module_key)


@pytest.mark.parametrize(
    "module_key",
    [
        "reports/v2",
        "tal till text",
        "SWE Models",
        "a%2Fb",
        "käll-modul",
        "-hidden",
        ".hidden",
        "nyckel?x=1",
        "a#b",
    ],
)
def test_module_key_rejects_non_url_safe_keys(module_key: str) -> None:
    with pytest.raises(ValidationError):
        ModuleCreate(name=module_key)


@pytest.mark.parametrize(
    "module_key",
    ["tal-till-text", "speech_to_text", "Reports.v2", Modules.ENEO_APPLICATIONS],
)
def test_module_key_preserves_url_safe_formats(
    module_key: Modules | str,
) -> None:
    module = ModuleCreate(name=module_key)

    assert module.name == module_key


def test_legacy_read_models_preserve_preexisting_nonconforming_keys() -> None:
    assert ModuleBase(name=" legacy-key ").name == " legacy-key "
    assert ModuleBase(name="SWE Models").name == "SWE Models"
    assert (
        ModuleInDB(id="00000000-0000-0000-0000-000000000001", name=" legacy-key ").name
        == " legacy-key "
    )
