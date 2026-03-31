from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from intric.flows.flow_run_evidence_bundle import RedactedEvidenceBundle

EVIDENCE_EXPORT_SCHEMA_VERSION = "flow-evidence-export.v2"


def render_evidence_json_export(*, bundle: RedactedEvidenceBundle) -> dict[str, object]:
    bundle_payload = bundle.to_dict()
    serialized_bundle = json.dumps(
        bundle_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": EVIDENCE_EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": hashlib.sha256(serialized_bundle).hexdigest(),
        "bundle": bundle_payload,
    }
