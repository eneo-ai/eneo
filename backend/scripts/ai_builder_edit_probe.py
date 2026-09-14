"""Paired saved-step edit probe: parent vs candidate.

The battle harness hardcodes target_kind=create and has no edit case, so slice 2's
own path is unmeasured by it. This drives, per stack:
  create a flow from a fixed prompt -> apply it -> N saved-step edits on step 1
and reports, per edit turn: outcome, repair count, whether the untouched steps came
back unchanged, and the turn's token usage.

usage: PROBE_KEY=... edit_probe.py <base-url> <space-id> <label> <repetitions>
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE, SPACE, LABEL, REPS = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
KEY = os.environ["PROBE_KEY"]
CREATE_PROMPT = (
    "Vi får in ansökningar om markupplåtelse som PDF. Flödet ska läsa ansökan, "
    "sammanfatta vad som söks, bedöma den mot våra regler och skriva ett "
    "beslutsdokument som levereras som PDF."
)
EDIT_PROMPT = (
    "Ändra instruktionen i det här steget så att den alltid listar vilka uppgifter "
    "som saknas i ansökan, som en punktlista."
)


def call(method, path, body=None, timeout=900):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "X-API-Key": KEY,
            "content-type": "application/json",
            "accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:300]}
    if "data:" in raw[:400] and "event:" in raw[:400]:
        evs = [
            json.loads(l[5:].strip())
            for l in raw.splitlines()
            if l.startswith("data:") and l[5:].strip().startswith("{")
        ]
        return {"_stream": evs}
    return json.loads(raw) if raw.strip() else {}


def session(sid):
    return call("GET", f"/flows/ai-builder/sessions/{sid}")


def turn(sid, message, **extra):
    return call(
        "POST",
        f"/flows/ai-builder/sessions/{sid}/messages",
        {
            "client_turn_id": str(uuid.uuid4()),
            "message": message,
            "ui_language": "sv",
            **extra,
        },
    )


def _requirements_summary(st):
    """The server asks for a structured confirmation, not a chat reply."""
    for msg in reversed(st.get("conversation") or []):
        rs = msg.get("requirements_summary") or msg.get("requirementsSummary")
        if isinstance(rs, dict):
            return rs
    lt = st.get("latest_turn") or {}
    rs = lt.get("requirements_summary")
    return rs if isinstance(rs, dict) else None


def drive_to_plan(sid, message, **extra):
    """Send one message, then confirm requirements the way the server expects."""
    turn(sid, message, **extra)
    for _ in range(8):
        st = session(sid)
        if st.get("latest_plan_id") and st.get("status") == "awaiting_approval":
            return st
        if st.get("status") in {"failed", "cancelled"}:
            return st
        rs = _requirements_summary(st)
        if rs is not None:
            payload = {
                "kind": "requirements_confirmation",
                "requirements_confirmed": True,
                "ui_language": "sv",
            }
            v = rs.get("requirements_version")
            if isinstance(v, str) and v:
                payload["requirements_version"] = v
            turn(sid, "", question_answer=payload, **extra)
        else:
            time.sleep(4)
    return session(sid)


def edit_turn_cost(sid):
    """Tokens and attempts this edit session actually spent at the provider."""
    d = call("GET", f"/flows/ai-builder/sessions/{sid}/_diagnostics/proposal-telemetry")
    calls = d.get("provider_calls")
    if not isinstance(calls, list):
        return {"unavailable": True}
    p = c = t = 0
    for rec in calls:
        u = rec.get("usage") or rec
        p += u.get("prompt_tokens") or 0
        c += u.get("completion_tokens") or 0
        t += u.get("total_tokens") or 0
    turns = d.get("proposal_turns")
    attempts = (
        sum(len(x.get("attempts") or []) for x in turns)
        if isinstance(turns, list)
        else None
    )
    return {
        "provider_calls": len(calls),
        "prompt_tokens": p,
        "completion_tokens": c,
        "total_tokens": t,
        "attempts": attempts,
    }


def steps_of(flow_id):
    f = call("GET", f"/flows/{flow_id}/")
    return [
        {
            k: s.get(k)
            for k in (
                "step_order",
                "user_description",
                "output_mode",
                "output_type",
                "input_type",
            )
        }
        for s in (f.get("steps") or [])
    ], f


out = {"label": LABEL, "base": BASE, "edits": []}

# --- build the flow once -----------------------------------------------------
s = call(
    "POST",
    "/flows/ai-builder/sessions",
    {"target_kind": "create", "space_id": SPACE, "force_new": True},
)
sid = s.get("session_id")
if not sid:
    print(json.dumps({**out, "fatal": "no create session", "resp": s}))
    sys.exit(1)
st = drive_to_plan(sid, CREATE_PROMPT)
plan_id = st.get("latest_plan_id")
out["create"] = {"status": st.get("status"), "plan_id": plan_id}
if not plan_id:
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1)
call("POST", f"/flows/ai-builder/plans/{plan_id}/approve")
created = call("POST", f"/flows/ai-builder/plans/{plan_id}/create")
flow_id = created.get("flow_id") or created.get("id")
out["flow_id"] = flow_id
if not flow_id:
    out["create_error"] = created
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1)
baseline, full = steps_of(flow_id)
out["baseline_steps"] = baseline
target = (full.get("steps") or [{}])[0]
target_step_id = target.get("id")
out["target_step_id"] = target_step_id

# --- the measured part: N saved-step edits on the same step ------------------
for i in range(REPS):
    es = call(
        "POST",
        "/flows/ai-builder/sessions",
        {
            "target_kind": "edit",
            "space_id": SPACE,
            "flow_id": flow_id,
            "force_new": True,
        },
    )
    esid = es.get("session_id")
    if not esid:
        out["edits"].append({"rep": i + 1, "error": es})
        continue
    t0 = time.time()
    st = drive_to_plan(
        esid,
        EDIT_PROMPT,
        edit_context={"kind": "saved_flow_step", "flow_step_id": target_step_id},
    )
    cost = edit_turn_cost(esid)
    after, _ = steps_of(flow_id)
    out["edits"].append(
        {
            "rep": i + 1,
            "status": st.get("status"),
            "has_plan": bool(st.get("latest_plan_id")),
            "seconds": round(time.time() - t0, 1),
            "cost": cost,
            "flow_unchanged_before_apply": after == baseline,
        }
    )
    print(
        f"[{LABEL}] rep {i + 1}: status={st.get('status')} plan={bool(st.get('latest_plan_id'))}",
        file=sys.stderr,
    )

print(json.dumps(out, ensure_ascii=False))
