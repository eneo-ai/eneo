"""Forecasts one daily series with a Timestral checkpoint.

Run by the tool runtime's sandbox child as ``python3 -I -B forecast.py <job.json>``. The job
holds validated numbers only (``null`` is a day without a value), the horizon, whether to also
forecast the last ``horizon`` days from the history before them, the checkpoint directory and
the number of threads. The checkpoint is read from that directory and nowhere else: nothing is
downloaded. Prints the P10, P50 and P90 forecasts, and the parameter count, as JSON.

A failure the user or operator can act on is printed as ``{"error": {"code", "message"}}``
with exit status 3; anything else is a crash, reported by the caller from stderr.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

LEVELS = (0.1, 0.5, 0.9)
CHECKPOINT_FILES = ("config.json", "model.safetensors")


class Refusal(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        result = forecast(job)
    except Refusal as refusal:
        print(json.dumps({"error": {"code": refusal.code, "message": str(refusal)}}))
        return 3
    print(json.dumps(result))
    return 0


def forecast(job: dict) -> dict:
    import torch

    # Before any work: the runtime decides how many cores one forecast may use.
    torch.set_num_threads(int(job["threads"]))
    torch.set_num_interop_threads(1)
    import numpy as np

    forecaster = load(Path(job["model_path"]))

    values = np.array([math.nan if v is None else float(v) for v in job["values"]], dtype=np.float32)
    horizon = int(job["horizon"])
    rows = [values]
    if job["holdout"]:
        # The same forecast made before the last `horizon` days: those days are left out, and the
        # row is padded at the start so both series share one batch. Each row is its own series.
        rows.append(np.concatenate([np.full(horizon, math.nan, dtype=np.float32), values[:-horizon]]))
    prediction = forecaster.forecast(np.stack(rows), prediction_length=horizon)

    def interval(row: int) -> dict[str, list[float]]:
        out = {}
        for name, level in zip(("p10", "p50", "p90"), LEVELS):
            series = prediction.quantile(level)[row, 0].tolist()
            if not all(math.isfinite(v) for v in series):
                raise Refusal("ENGINE_FAILED", "The forecast model returned values that are not numbers.")
            out[name] = series
        return out

    result = {
        "forecast": interval(0),
        "parameters": sum(p.numel() for p in forecaster.model.parameters()),
    }
    if job["holdout"]:
        result["holdout"] = interval(1)
    return result


def load(checkpoint: Path):
    """The checkpoint at ``checkpoint``, or a refusal saying why it cannot be used.

    Everything that can go wrong while reading it (missing or unreadable files, a config that
    is not Timestral's, weights that do not decode or do not fit) means the operator must
    install another checkpoint, so all of it is MODEL_UNAVAILABLE. A missing directory never
    reaches the loader, which would take its name for a Hugging Face Hub repository.
    """
    try:
        missing = [name for name in CHECKPOINT_FILES if not (checkpoint / name).is_file()]
        if missing:
            raise Refusal(
                "MODEL_UNAVAILABLE",
                f"The forecast model is not installed: {checkpoint} has no {' or '.join(missing)}.",
            )
        from timestral import TimestralForecaster

        forecaster = TimestralForecaster.from_pretrained(checkpoint, local_files_only=True)
    except Refusal:
        raise
    except Exception as error:  # noqa: BLE001 - every loading failure is the checkpoint's
        raise Refusal(
            "MODEL_UNAVAILABLE",
            f"The forecast model at {checkpoint} could not be loaded as a Timestral checkpoint: "
            f"{type(error).__name__}: {str(error)[:300]}",
        ) from error
    if not all(level in forecaster.quantile_levels for level in LEVELS):
        raise Refusal("MODEL_UNAVAILABLE", "The forecast model does not predict P10, P50 and P90.")
    return forecaster


if __name__ == "__main__":
    sys.exit(main())
