"""The inline backfill must not initialize the remote object-store adapter."""

import json
import subprocess
import sys
from pathlib import Path


def test_file_icon_backfill_import_does_not_load_s3_adapter() -> None:
    source_root = Path(__file__).resolve().parents[3] / "src"
    probe = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(source_root)!r})\n"
        "import eneo.object_content.file_icon_backfill\n"
        "print(json.dumps(sorted(name for name in sys.modules "
        "if name == 'eneo.object_content.s3_object_store' "
        "or name == 'botocore' or name.startswith('botocore.'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []
