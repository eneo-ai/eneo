import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { describeSkipReason, skipReasonKind } from "./skipReasons";

describe("describeSkipReason", () => {
  it.each([
    ["Unsupported file type (image)", m.skip_reason_unsupported_type({ label: "image" })],
    [
      "Unsupported file type (legacy Word .doc, save as .docx)",
      m.skip_reason_unsupported_type({ label: "legacy Word .doc, save as .docx" })
    ],
    ["No text layer (scanned document; OCR is not supported)", m.skip_reason_no_text_layer()],
    ["Empty or unreadable content", m.skip_reason_empty_content()],
    ["File too large (exceeds 50 MB limit)", m.skip_reason_file_too_large({ limit: "50" })],
    ["File too large (exceeds 0.5 MB limit)", m.skip_reason_file_too_large({ limit: "0.5" })],
    [
      "Exceeds extraction limit (1048576 bytes of text)",
      m.skip_reason_extraction_limit({ limit: m.skip_reason_limit_text_bytes({ count: 1048576 }) })
    ],
    [
      "Exceeds extraction limit (500 PDF pages)",
      m.skip_reason_extraction_limit({ limit: m.skip_reason_limit_pdf_pages({ count: 500 }) })
    ],
    [
      "Exceeds extraction limit (something new)",
      m.skip_reason_extraction_limit({ limit: "something new" })
    ],
    [
      "Error: Incomplete download of 'Protokoll (2).pdf' (1024 of 4096 bytes)",
      m.skip_reason_incomplete_download()
    ],
    ["Error: Password-protected file", m.skip_reason_password_protected()],
    ["Error: Corrupt or malformed file", m.skip_reason_corrupt_file()],
    [
      "Error: TimeoutError while extracting pdf",
      m.skip_reason_error({ detail: "TimeoutError while extracting pdf" })
    ],
    ["  Missing item id ", "Missing item id"],
    ["Folder scope path unavailable", "Folder scope path unavailable"]
  ])("%s", (reason, expected) => {
    expect(describeSkipReason(reason)).toBe(expected);
  });
});

describe("skipReasonKind", () => {
  it.each([
    ["Unsupported file type (image)", "unsupported_type"],
    ["No text layer (scanned document; OCR is not supported)", "no_text_layer"],
    ["Empty or unreadable content", "empty_content"],
    ["File too large (exceeds 50 MB limit)", "file_too_large"],
    ["Exceeds extraction limit (500 PDF pages)", "extraction_limit"],
    ["Error: Incomplete download of 'a.pdf' (1 of 2 bytes)", "incomplete_download"],
    ["Error: Password-protected file", "password_protected"],
    ["Error: Corrupt or malformed file", "corrupt_file"],
    ["Error: TimeoutError while extracting pdf", "error"],
    ["Folder scope path unavailable", "error"]
  ] as const)("%s", (reason, kind) => {
    expect(skipReasonKind(reason)).toBe(kind);
  });
});
