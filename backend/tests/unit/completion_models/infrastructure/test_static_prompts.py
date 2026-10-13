"""The attached-file instruction gates reads on need.

A reference entry hands the model a capability, not a task. The instruction
must make a bare attachment (a greeting with a file) end in a reply, not in
a tool call that reads, summarizes or ships the file to an external server,
while keeping the rules that stop the model from refusing a readable file.
"""

from eneo.completion_models.infrastructure.static_prompts import (
    ATTACHED_FILE_REFERENCES_INSTRUCTION,
)


def test_reads_are_conditional_on_the_message_needing_the_content():
    instruction = ATTACHED_FILE_REFERENCES_INSTRUCTION
    assert "only when answering the user's message requires its content" in (
        instruction
    )
    assert "not a request to read, summarize or ingest it" in instruction
    assert "ask what the user wants done with it" in instruction


def test_readability_and_tool_arbitration_rules_are_kept():
    instruction = ATTACHED_FILE_REFERENCES_INSTRUCTION
    assert (
        "never judge from the file_ref whether a file is readable"
        in instruction.lower()
    )
    assert "never ask the user to re-upload" in instruction
    assert "accepts every file_ref" in instruction
    assert '"kind": "image"' in instruction


def test_file_handles_are_passed_unchanged_without_constructing_urls():
    instruction = ATTACHED_FILE_REFERENCES_INSTRUCTION
    assert "pass file_ref unchanged" in instruction
    assert "Never construct, copy or repair download URLs or tokens" in instruction
