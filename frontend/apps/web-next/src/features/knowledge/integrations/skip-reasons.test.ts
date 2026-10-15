import { describe, expect, it } from "vitest";
import { createTranslator } from "next-intl";
import sv from "@/lib/i18n/messages/sv.json";
import { describeSkipReason, skipReasonKind } from "./skip-reasons";

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

describe("describeSkipReason", () => {
  it.each([
    ["Unsupported file type (image)", t("skip_reason_unsupported_type", { label: "image" })],
    [
      "Unsupported file type (legacy Word .doc, save as .docx)",
      t("skip_reason_unsupported_type", { label: "legacy Word .doc, save as .docx" })
    ],
    ["No text layer (scanned document; OCR is not supported)", t("skip_reason_no_text_layer")],
    ["Empty or unreadable content", t("skip_reason_empty_content")],
    ["File too large (exceeds 50 MB limit)", t("skip_reason_file_too_large", { limit: "50" })],
    ["File too large (exceeds 0.5 MB limit)", t("skip_reason_file_too_large", { limit: "0.5" })],
    [
      "Exceeds extraction limit (1048576 bytes of text)",
      t("skip_reason_extraction_limit", {
        limit: t("skip_reason_limit_text_bytes", { count: 1048576 })
      })
    ],
    [
      "Exceeds extraction limit (500 PDF pages)",
      t("skip_reason_extraction_limit", { limit: t("skip_reason_limit_pdf_pages", { count: 500 }) })
    ],
    [
      "Exceeds extraction limit (something new)",
      t("skip_reason_extraction_limit", { limit: "something new" })
    ],
    [
      "Error: Incomplete download of 'Protokoll (2).pdf' (1024 of 4096 bytes)",
      t("skip_reason_incomplete_download")
    ],
    ["Error: Password-protected file", t("skip_reason_password_protected")],
    ["Error: Corrupt or malformed file", t("skip_reason_corrupt_file")],
    [
      "Error: TimeoutError while extracting pdf",
      t("skip_reason_error", { detail: "TimeoutError while extracting pdf" })
    ],
    ["  Missing item id ", "Missing item id"],
    ["Folder scope path unavailable", "Folder scope path unavailable"]
  ])("%s", (reason, expected) => {
    expect(describeSkipReason(reason, t)).toBe(expected);
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
