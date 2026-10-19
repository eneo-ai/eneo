import { describe, expect, it } from "vitest";
import { createTranslator } from "next-intl";
import sv from "@/lib/i18n/messages/sv.json";
import {
  describeErrorDetail,
  describeSkipReason,
  skipReasonKind,
  type SkipReason,
  type SkipReasonCode
} from "./skip-reasons";

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

// One example of every code the backend writes (backend/src/eneo/integration/domain/skip_reasons.py).
const EXAMPLES: Record<SkipReasonCode, [SkipReason, string]> = {
  unsupported_type: [
    { code: "unsupported_type", params: { label: "legacy Word .doc, save as .docx" } },
    t("skip_reason_unsupported_type", { label: t("skip_reason_type_legacy_word") })
  ],
  no_text_layer: [{ code: "no_text_layer", params: {} }, t("skip_reason_no_text_layer")],
  unchanged: [{ code: "unchanged", params: {} }, "Redan indexerad och oförändrad"],
  set_aside: [
    { code: "set_aside", params: { attempts: 3, detail: "HTTP 500" } },
    "Lagd åt sidan efter 3 misslyckade försök och försöks igen senare: HTTP 500"
  ],
  empty_content: [{ code: "empty_content", params: {} }, t("skip_reason_empty_content")],
  file_too_large: [
    { code: "file_too_large", params: { limit_mb: "50" } },
    t("skip_reason_file_too_large", { limit: "50" })
  ],
  extraction_limit: [
    { code: "extraction_limit", params: { limit: "resource" } },
    t("skip_reason_extraction_limit", { limit: t("skip_reason_limit_resource") })
  ],
  incomplete_download: [
    {
      code: "incomplete_download",
      params: { detail: "Incomplete download of 'a' (1 of 2 bytes)" }
    },
    t("skip_reason_incomplete_download")
  ],
  password_protected: [
    { code: "password_protected", params: {} },
    t("skip_reason_password_protected")
  ],
  corrupt_file: [{ code: "corrupt_file", params: {} }, t("skip_reason_corrupt_file")],
  http_error: [
    { code: "http_error", params: { status: 403, message: "Forbidden" } },
    t("skip_reason_http_forbidden")
  ],
  removal_failed: [
    { code: "removal_failed", params: { what: "unextractable", detail: "Database error" } },
    t("skip_reason_removal_failed", { detail: t("skip_reason_detail_database") })
  ],
  listing_failed: [
    { code: "listing_failed", params: { detail: "HTTP 503 Service Unavailable" } },
    t("skip_reason_listing_failed", { detail: t("skip_reason_detail_http", { status: 503 }) })
  ],
  scope_path_unavailable: [
    { code: "scope_path_unavailable", params: {} },
    t("skip_reason_scope_path_unavailable")
  ],
  missing_item_id: [{ code: "missing_item_id", params: {} }, t("skip_reason_missing_item_id")],
  error: [
    { code: "error", params: { detail: "Cache service error" } },
    t("skip_reason_error", { detail: t("skip_reason_detail_cache") })
  ]
};

describe("describeSkipReason", () => {
  it.each(Object.entries(EXAMPLES))("translates %s by its code", (_code, [skip, expected]) => {
    // The English text never decides: a coded reason reads the same whatever it says.
    expect(describeSkipReason({ ...skip, reason: "English text the UI must not show" }, t)).toBe(
      expected
    );
  });

  it.each([
    [
      { limit: "text_bytes", value: 1048576 },
      t("skip_reason_limit_text_bytes", { count: 1048576 })
    ],
    [{ limit: "pdf_pages", value: 500 }, t("skip_reason_limit_pdf_pages", { count: 500 })],
    [{ limit: "deadline" }, t("skip_reason_limit_deadline")],
    [{ limit: "output" }, t("skip_reason_limit_output")],
    [{ limit: "other", detail: "something new" }, "something new"]
  ])("names the extraction limit %o", (params, limit) => {
    expect(describeSkipReason({ code: "extraction_limit", params }, t)).toBe(
      t("skip_reason_extraction_limit", { limit })
    );
  });

  it.each([
    [404, t("skip_reason_http_gone", { status: 404 })],
    [410, t("skip_reason_http_gone", { status: 410 })],
    [429, t("skip_reason_http_throttled")],
    [500, t("skip_reason_http_other", { status: 500 })]
  ])("says what HTTP %s means", (status, expected) => {
    expect(describeSkipReason({ code: "http_error", params: { status, message: "x" } }, t)).toBe(
      expected
    );
  });

  it("adds that the next sync tries again", () => {
    expect(
      describeSkipReason({ code: "http_error", params: { status: 503 }, retry: true }, t)
    ).toBe(t("skip_reason_with_retry", { reason: t("skip_reason_http_other", { status: 503 }) }));
  });

  it("names a type in the viewer's language, and passes names without words through", () => {
    for (const [label, expected] of [
      ["image", "bild"],
      ["Outlook .msg", "Outlook .msg"],
      [".zip", ".zip"],
      ["toString", "toString"]
    ] as const) {
      expect(describeSkipReason({ code: "unsupported_type", params: { label } }, t)).toBe(
        t("skip_reason_unsupported_type", { label: expected })
      );
    }
  });

  it("names an item SharePoint offers no download for", () => {
    expect(
      describeSkipReason(
        { code: "error", params: { detail: "SharePoint offers no download for this item" } },
        t
      )
    ).toBe(t("skip_reason_error", { detail: "SharePoint erbjuder ingen nedladdning av objektet" }));
  });

  it("lets a set-aside file say itself when it is tried again", () => {
    const skip: SkipReason = {
      code: "set_aside",
      params: { attempts: 3, detail: "HTTP 500" },
      retry: true
    };
    expect(describeSkipReason(skip, t)).toBe(describeSkipReason({ ...skip, retry: false }, t));
  });

  it("does not double the full stop before the retry note", () => {
    expect(describeSkipReason({ reason: "Server busy.", retry: true }, t)).toBe(
      "Server busy. Försöks igen vid nästa synk"
    );
  });

  it("shows the text only for a code this client does not know", () => {
    expect(describeSkipReason({ reason: "  Something new  " }, t)).toBe("Something new");
    expect(
      describeSkipReason({ code: "brand_new" as SkipReasonCode, reason: "Brand new reason" }, t)
    ).toBe("Brand new reason");
  });
});

describe("describeErrorDetail", () => {
  it.each([
    ["Database error", t("skip_reason_detail_database")],
    ["Connection error", t("skip_reason_detail_connection")],
    ["Request timed out", t("skip_reason_detail_timeout")],
    ["HTTP 429 Too Many Requests", t("skip_reason_detail_http", { status: 429 })],
    ["TimeoutError while extracting pdf", "TimeoutError while extracting pdf"]
  ])("%s", (detail, expected) => {
    expect(describeErrorDetail(detail, t)).toBe(expected);
  });
});

describe("skipReasonKind", () => {
  it("is the code, and an error for anything unknown", () => {
    expect(skipReasonKind({ code: "no_text_layer" })).toBe("no_text_layer");
    expect(skipReasonKind({ reason: "No text layer" })).toBe("error");
    expect(skipReasonKind({ code: "brand_new" as SkipReasonCode })).toBe("error");
  });
});
