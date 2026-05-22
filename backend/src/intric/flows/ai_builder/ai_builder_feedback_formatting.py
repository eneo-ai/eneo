from __future__ import annotations


def format_revision_feedback(title: str, issues: list[str]) -> str:
    if not issues:
        return title
    numbered = "\n".join(
        f"{index}. {issue}" for index, issue in enumerate(issues, start=1)
    )
    return f"{title}:\n{numbered}"
