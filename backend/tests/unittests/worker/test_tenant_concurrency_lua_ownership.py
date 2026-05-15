"""Ownership tests for tenant limiter Redis slot Lua execution."""

import re
from pathlib import Path


def test_tenant_concurrency_does_not_inline_slot_lua_eval():
    source_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "intric"
        / "worker"
        / "tenant_concurrency.py"
    )
    source = source_path.read_text()

    raw_eval_pattern = re.compile(
        r"getattr\(\s*self\.redis\s*,\s*['\"]ev['\"]\s*\+\s*['\"]al['\"]\s*\)"
    )
    slot_script_constant_pattern = re.compile(r"LuaScripts\.(?:ACQUIRE|RELEASE)_SLOT\b")

    assert raw_eval_pattern.search(source) is None
    assert slot_script_constant_pattern.search(source) is None
    assert "LuaScripts.acquire_slot" in source
    assert "LuaScripts.release_slot" in source
