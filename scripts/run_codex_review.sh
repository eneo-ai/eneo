#!/usr/bin/env bash
# run_codex_review.sh — reliable wrapper for Codex tier-2 reviews.
#
# WHY: bare `codex exec` runs have hung silently in this project for up
# to 22 minutes at a time. The root cause was one of two things:
#   1. Prompt passed as `"$(cat prompt.md)"` or piped into `tee | tail`
#      creates extra processes that outlive codex and hold the stdout
#      pipe open, so external monitors see no EOF and never release.
#   2. MCP child servers spawned by codex (filesystem, shell, etc.)
#      keep their pipes open after the codex parent dies, producing
#      the same pipe-alive-but-no-progress failure mode.
#
# This wrapper fixes both by:
#   - Piping the prompt via stdin (no `$(cat …)` subshell churn).
#   - Redirecting stdout+stderr directly to a log file (no tee/tail
#     pipe).
#   - Running codex in its own session/process-group via an
#     `os.setsid()` python shim (portable across macOS/Linux — macOS
#     ships without `setsid(1)`), so `kill -TERM -<pgid>` later
#     reaches every descendant including MCP child servers.
#   - A bytes-stalled detector: if the stdout log does not grow for
#     STALL_SECS, we assume codex is wedged and abort the whole group.
#   - A hard watchdog: after WATCHDOG_SECS we abort no matter what.
#   - A clear done-contract for external monitors: when the verdict
#     file is populated and non-empty, we touch <last>.ready and
#     print `REVIEW_READY <bytes>` as the last line on stdout.
#
# Usage:
#   Fresh (iter-1):
#     scripts/run_codex_review.sh <prompt.md> <last.md> [stdout.log]
#     → writes <last.md>.session_id alongside the verdict.
#
#   Resume (iter-2 / iter-3 / BLOCKER loopback):
#     scripts/run_codex_review.sh --resume <prev_last.md> <followup.md> <last.md> [stdout.log]
#     → reads <prev_last.md>.session_id and calls `codex exec resume
#       <SESSION_ID>` (never `--last`, because `--last` is global
#       state and can target a session you started for a different
#       project in between iter-1 and iter-2).
#
# Resume mode is the standard review loop: iter-1 finds issues, you
# apply/reject them, iter-2 re-reviews and (ideally) ACKs. Your
# follow-up prompt only needs: (a) which findings you applied, (b)
# which you rejected + why, (c) new concerns you spotted, (d) the
# re-review ask — codex rereads its own prior responses as context,
# so never re-paste the original review prompt.
#
# Exit codes:
#   0  codex finished and wrote a non-empty verdict file
#   1  usage error
#   2  codex exited but produced no verdict (read the stdout log)
#   3  stall-detector aborted (bytes not growing)
#   4  hard watchdog aborted
#
# Env knobs (override at call site):
#   CODEX_MODEL         default: gpt-5.4
#   CODEX_EFFORT        default: xhigh
#   STALL_SECS          default: 300    (no-growth window before abort; 5 min)
#   STALL_MIN_BYTES     default: 200    (stall timer arms once output crosses this)
#   WATCHDOG_SECS       default: 1500   (hard upper bound; 25 min)

set -u
set -o pipefail

RESUME=0
PREV_LAST_FILE=""
if [[ "${1:-}" == "--resume" ]]; then
  RESUME=1
  shift
  PREV_LAST_FILE=${1:-}
  shift || true
fi

PROMPT_FILE=${1:-}
LAST_FILE=${2:-}
STDOUT_LOG=${3:-}

if [[ -z "$PROMPT_FILE" || -z "$LAST_FILE" ]]; then
  cat >&2 <<'USAGE'
usage:
  scripts/run_codex_review.sh                       <prompt.md> <last.md> [stdout.log]
  scripts/run_codex_review.sh --resume <prev_last.md> <followup.md> <last.md> [stdout.log]

--resume requires the prior iteration's last-file path (we read its
sibling <prev_last.md>.session_id to pin the explicit session id —
never `--last`, because that is global state).
USAGE
  exit 1
fi

if [[ ! -s "$PROMPT_FILE" ]]; then
  echo "error: prompt file missing or empty: $PROMPT_FILE" >&2
  exit 1
fi

SESSION_ID=""
if (( RESUME == 1 )); then
  if [[ -z "$PREV_LAST_FILE" ]]; then
    echo "error: --resume needs <prev_last.md> before <followup.md>" >&2
    exit 1
  fi
  SID_FILE="${PREV_LAST_FILE}.session_id"
  if [[ ! -s "$SID_FILE" ]]; then
    echo "error: session id sidecar missing or empty: $SID_FILE" >&2
    echo "       (iter-1 runs leave this file next to the verdict; if" >&2
    echo "       it is gone, you must start a fresh session instead)" >&2
    exit 1
  fi
  SESSION_ID=$(tr -d '[:space:]' <"$SID_FILE")
  if [[ -z "$SESSION_ID" ]]; then
    echo "error: session id in $SID_FILE is blank" >&2
    exit 1
  fi
fi

STDOUT_LOG=${STDOUT_LOG:-"${LAST_FILE%.md}_stdout.log"}
: >"$LAST_FILE"
: >"$STDOUT_LOG"

CODEX_MODEL=${CODEX_MODEL:-gpt-5.4}
CODEX_EFFORT=${CODEX_EFFORT:-xhigh}
# Stall timing — calibrated for xhigh reasoning on review-sized prompts.
# Codex prints a ~400-byte banner immediately, then may go quiet for
# several minutes while reasoning. Arm the detector once the banner
# lands (MIN_BYTES=200) so pre-banner wedging is caught, but keep the
# no-growth window generous (SECS=300 = 5 min) so deep reasoning does
# not false-trigger.
STALL_SECS=${STALL_SECS:-300}
STALL_MIN_BYTES=${STALL_MIN_BYTES:-200}
WATCHDOG_SECS=${WATCHDOG_SECS:-1500}

CODEX_ARGS=(codex exec)
if (( RESUME == 1 )); then
  # Explicit session id (never `--last`, which is global state and
  # unsafe if another codex run lands between iter-1 and iter-2).
  # `codex exec resume` does NOT accept -C or -s (workdir and sandbox
  # are inherited from the recorded session), so we pass a smaller
  # flag subset here.
  CODEX_ARGS+=(
    resume "$SESSION_ID"
    --skip-git-repo-check
    -m "$CODEX_MODEL"
    -c model_reasoning_effort="$CODEX_EFFORT"
    --full-auto
    --output-last-message "$LAST_FILE"
    -
  )
else
  CODEX_ARGS+=(
    --skip-git-repo-check
    -C "$PWD"
    -m "$CODEX_MODEL"
    -c model_reasoning_effort="$CODEX_EFFORT"
    -s read-only
    --full-auto
    --output-last-message "$LAST_FILE"
    -
  )
fi

# Launch codex in its own process group via a tiny Python shim. We
# cannot rely on `setsid(1)` because macOS ships without it;
# `os.setsid()` does the same thing portably — new session, new
# process group, no controlling tty — so `kill -TERM -<pgid>` later
# reaches every descendant (including MCP child servers) even if we
# never learn their pids.
python3 -c '
import os, sys
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
' "${CODEX_ARGS[@]}" \
  <"$PROMPT_FILE" \
  >"$STDOUT_LOG" 2>&1 &
CODEX_PID=$!

# On macOS `ps -o pgid=` returns the process-group id.
CODEX_PGID=$(ps -o pgid= -p "$CODEX_PID" 2>/dev/null | tr -d ' ')
if [[ -z "$CODEX_PGID" ]]; then
  CODEX_PGID=$CODEX_PID
fi

cleanup() {
  # Negative pid ⇒ signal the whole group. Escalate TERM → KILL.
  if kill -0 "$CODEX_PID" 2>/dev/null; then
    kill -TERM "-$CODEX_PGID" 2>/dev/null || true
    sleep 2
    kill -KILL "-$CODEX_PGID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

started=$(date +%s)
last_bytes=0
last_growth=$started

while kill -0 "$CODEX_PID" 2>/dev/null; do
  now=$(date +%s)
  elapsed=$((now - started))

  # Hard watchdog — nothing should legitimately take this long.
  if (( elapsed >= WATCHDOG_SECS )); then
    echo "WATCHDOG elapsed=${elapsed}s — aborting" >&2
    cleanup
    trap - EXIT
    exit 4
  fi

  bytes=0
  if [[ -f "$STDOUT_LOG" ]]; then
    bytes=$(wc -c <"$STDOUT_LOG" | tr -d ' ')
  fi

  if (( bytes > last_bytes )); then
    last_bytes=$bytes
    last_growth=$now
  elif (( bytes >= STALL_MIN_BYTES )); then
    stalled_for=$((now - last_growth))
    if (( stalled_for >= STALL_SECS )); then
      echo "STALL bytes=${bytes} no_growth_for=${stalled_for}s — aborting" >&2
      cleanup
      trap - EXIT
      exit 3
    fi
  fi

  sleep 5
done

wait "$CODEX_PID" 2>/dev/null
rc=$?
trap - EXIT

verdict_bytes=0
if [[ -s "$LAST_FILE" ]]; then
  verdict_bytes=$(wc -c <"$LAST_FILE" | tr -d ' ')
fi

if (( verdict_bytes == 0 )); then
  echo "ERROR codex exited rc=${rc} but produced no verdict (see ${STDOUT_LOG})" >&2
  exit 2
fi

# Capture this run's session id from the banner so a later --resume
# can pin it explicitly. Codex prints a single line like:
#   session id: 019db6e7-ca05-7461-bde0-2cff8d0a670c
# in the first ~20 lines of the banner. We grep case-insensitive and
# take the first hit.
SID=$(grep -iE '^session id:' "$STDOUT_LOG" | head -1 | awk '{print $NF}' | tr -d '[:space:]')
if [[ -n "$SID" ]]; then
  printf '%s\n' "$SID" >"${LAST_FILE}.session_id"
fi

# Done-contract for external monitors: a sibling .ready marker + a
# single sentinel line on stdout so a `Monitor` stream can key on it.
: >"${LAST_FILE}.ready"
echo "REVIEW_READY ${verdict_bytes}"
exit 0
