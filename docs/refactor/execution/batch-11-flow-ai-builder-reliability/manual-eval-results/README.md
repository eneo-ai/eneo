# Manual Eval Results

This directory is for curated, redacted AI Builder manual API scorecards only.

Committed files may include:

- redacted scorecards that contain no raw prompt text, API keys, uploaded files,
  raw response bodies, transcripts, or unredacted UUIDs;
- short comparison summaries that point to scorecard filenames and Batch 11
  slice ids.

Use the harness filename pattern
`<prompt_id>__<evaluation_mode>__run_<n>.json` for individual scorecards.
For combined curated baselines, use `<slice-id>-<YYYYMMDDTHHMMSSZ>.json`.

Do not commit:

- `raw-*` directories or files;
- `*.local.json` files;
- downloaded artifacts, transcripts, uploaded fixtures, signed URLs, API keys,
  raw SSE streams, or unredacted API responses.

The root `.gitignore` excludes `raw-*` and `*.local.json` under this directory.
Keep raw local evidence outside git or in those ignored paths.
