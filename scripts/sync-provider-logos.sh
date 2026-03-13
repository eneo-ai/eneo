#!/usr/bin/env python3
"""
Sync provider logos from LiteLLM's repository.
Run this when upgrading LiteLLM or when new providers are added.

Usage: ./scripts/sync-provider-logos.sh
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOGO_DIR = SCRIPT_DIR.parent / "frontend/apps/web/src/lib/assets/provider-logos"
API_URL = "https://api.github.com/repos/BerriAI/litellm/contents/ui/litellm-dashboard/public/assets/logos"
RAW_BASE = "https://raw.githubusercontent.com/BerriAI/litellm/main/ui/litellm-dashboard/public/assets/logos"

IMAGE_EXTS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}

# Rename litellm filenames to our provider_type names
RENAME = {
    "openai_small": "openai",
    "microsoft_azure": "azure",
    "google": "gemini",
    "togetherai": "together_ai",
    "fireworks": "fireworks_ai",
    "perplexity-ai": "perplexity",
    "assemblyai_small": "assemblyai",
}

# Skip non-provider files (tools, infra, monitoring, etc.)
SKIP = {
    "a2a_agent", "aim_logo", "aim_security", "aporia", "arize", "braintrust",
    "cometapi", "cursor", "datadog", "enkrypt_ai", "guardrails_ai", "lago",
    "lakeraai", "langfuse", "langsmith", "langgraph", "lasso", "litellm",
    "litellm_logo", "llm_guard", "lmstudio", "mcp_logo", "milvus",
    "noma_security", "openmeter", "otel", "palo_alto_networks", "pangea",
    "parallel_ai", "pillar", "postgresql", "presidio", "prompt_security",
    "pydantic", "s3_vector", "secret_detect", "topaz", "v0", "vercel",
    "github", "github_copilot",
}


def main():
    print("Fetching logo list from LiteLLM...")
    result = subprocess.run(
        ["curl", "-sfL", API_URL], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("ERROR: Failed to fetch file list from GitHub API")
        sys.exit(1)

    files = json.loads(result.stdout)

    # Existing logos (by base name, any extension)
    existing = {f.stem for f in LOGO_DIR.iterdir() if f.suffix in IMAGE_EXTS}

    new_count = 0
    for f in sorted(files, key=lambda x: x["name"]):
        name = f["name"]
        stem = Path(name).stem
        ext = Path(name).suffix

        if ext not in IMAGE_EXTS:
            continue
        if stem in SKIP:
            continue

        target = RENAME.get(stem, stem)

        if target in existing:
            continue

        # Download
        dest = LOGO_DIR / f"{target}{ext}"
        dl = subprocess.run(
            ["curl", "-sfL", f"{RAW_BASE}/{name}", "-o", str(dest)],
            capture_output=True,
        )
        if dl.returncode == 0:
            print(f"  NEW: {target}{ext} (from {name})")
            existing.add(target)
            new_count += 1
        else:
            print(f"  FAIL: {target}{ext} (from {name})")

    total = sum(1 for f in LOGO_DIR.iterdir() if f.suffix in IMAGE_EXTS)
    print(f"\nDone. {new_count} new logos downloaded. Total: {total}")
    print("No code changes needed — logos are auto-discovered at build time.")


if __name__ == "__main__":
    main()
