import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import {
  describeErrorDetail,
  describeSkipReason,
  skipReasonKind,
  type SkipReason,
  type SkipReasonCode
} from "./skipReasons";

// One example of every code the backend writes (backend/src/eneo/integration/domain/skip_reasons.py).
const EXAMPLES: Record<SkipReasonCode, [SkipReason, string]> = {
  unsupported_type: [
    { code: "unsupported_type", params: { label: "legacy Word .doc, save as .docx" } },
    m.skip_reason_unsupported_type({ label: m.skip_reason_type_legacy_word() })
  ],
  no_text_layer: [{ code: "no_text_layer", params: {} }, m.skip_reason_no_text_layer()],
  unchanged: [{ code: "unchanged", params: {} }, m.skip_reason_unchanged()],
  set_aside: [
    { code: "set_aside", params: { attempts: 3, detail: "HTTP 500" } },
    m.skip_reason_set_aside({ attempts: 3, detail: m.skip_reason_detail_http({ status: 500 }) })
  ],
  empty_content: [{ code: "empty_content", params: {} }, m.skip_reason_empty_content()],
  file_too_large: [
    { code: "file_too_large", params: { limit_mb: "50" } },
    m.skip_reason_file_too_large({ limit: "50" })
  ],
  extraction_limit: [
    { code: "extraction_limit", params: { limit: "resource" } },
    m.skip_reason_extraction_limit({ limit: m.skip_reason_limit_resource() })
  ],
  incomplete_download: [
    {
      code: "incomplete_download",
      params: { detail: "Incomplete download of 'a' (1 of 2 bytes)" }
    },
    m.skip_reason_incomplete_download()
  ],
  password_protected: [
    { code: "password_protected", params: {} },
    m.skip_reason_password_protected()
  ],
  corrupt_file: [{ code: "corrupt_file", params: {} }, m.skip_reason_corrupt_file()],
  http_error: [
    { code: "http_error", params: { status: 403, message: "Forbidden" } },
    m.skip_reason_http_forbidden()
  ],
  removal_failed: [
    { code: "removal_failed", params: { what: "unextractable", detail: "Database error" } },
    m.skip_reason_removal_failed({ detail: m.skip_reason_detail_database() })
  ],
  listing_failed: [
    { code: "listing_failed", params: { detail: "HTTP 503 Service Unavailable" } },
    m.skip_reason_listing_failed({ detail: m.skip_reason_detail_http({ status: 503 }) })
  ],
  scope_path_unavailable: [
    { code: "scope_path_unavailable", params: {} },
    m.skip_reason_scope_path_unavailable()
  ],
  missing_item_id: [{ code: "missing_item_id", params: {} }, m.skip_reason_missing_item_id()],
  error: [
    { code: "error", params: { detail: "Cache service error" } },
    m.skip_reason_error({ detail: m.skip_reason_detail_cache() })
  ]
};

describe("describeSkipReason", () => {
  it.each(Object.entries(EXAMPLES))("translates %s by its code", (_code, [skip, expected]) => {
    // The English text never decides: a coded reason reads the same whatever it says.
    expect(describeSkipReason({ ...skip, reason: "English text the UI must not show" })).toBe(
      expected
    );
  });

  it.each([
    [{ limit: "text_bytes", value: 1048576 }, m.skip_reason_limit_text_bytes({ count: 1048576 })],
    [{ limit: "pdf_pages", value: 500 }, m.skip_reason_limit_pdf_pages({ count: 500 })],
    [{ limit: "deadline" }, m.skip_reason_limit_deadline()],
    [{ limit: "output" }, m.skip_reason_limit_output()],
    [{ limit: "other", detail: "something new" }, "something new"]
  ])("names the extraction limit %o", (params, limit) => {
    expect(describeSkipReason({ code: "extraction_limit", params })).toBe(
      m.skip_reason_extraction_limit({ limit })
    );
  });

  it.each([
    [404, m.skip_reason_http_gone({ status: 404 })],
    [410, m.skip_reason_http_gone({ status: 410 })],
    [429, m.skip_reason_http_throttled()],
    [500, m.skip_reason_http_other({ status: 500 })]
  ])("says what HTTP %s means", (status, expected) => {
    expect(describeSkipReason({ code: "http_error", params: { status, message: "x" } })).toBe(
      expected
    );
  });

  it("adds that the next sync tries again", () => {
    expect(describeSkipReason({ code: "http_error", params: { status: 503 }, retry: true })).toBe(
      m.skip_reason_with_retry({ reason: m.skip_reason_http_other({ status: 503 }) })
    );
  });

  it("names a type in the viewer's language, and passes names without words through", () => {
    for (const [label, expected] of [
      ["image", m.skip_reason_type_image()],
      ["Outlook .msg", "Outlook .msg"],
      [".zip", ".zip"],
      ["toString", "toString"]
    ]) {
      expect(describeSkipReason({ code: "unsupported_type", params: { label } })).toBe(
        m.skip_reason_unsupported_type({ label: expected })
      );
    }
  });

  it("names an item SharePoint offers no download for", () => {
    expect(
      describeSkipReason({
        code: "error",
        params: { detail: "SharePoint offers no download for this item" }
      })
    ).toBe(m.skip_reason_error({ detail: m.skip_reason_detail_no_download() }));
  });

  it("lets a set-aside file say itself when it is tried again", () => {
    const params = { attempts: 3, detail: "HTTP 500" };
    expect(describeSkipReason({ code: "set_aside", params, retry: true })).toBe(
      m.skip_reason_set_aside({ attempts: 3, detail: m.skip_reason_detail_http({ status: 500 }) })
    );
  });

  it("does not double the full stop before the retry note", () => {
    expect(describeSkipReason({ reason: "Server busy.", retry: true })).toBe(
      m.skip_reason_with_retry({ reason: "Server busy" })
    );
  });

  it("shows the text only for a code this client does not know", () => {
    expect(describeSkipReason({ reason: "  Something new  " })).toBe("Something new");
    expect(
      describeSkipReason({ code: "brand_new" as SkipReasonCode, reason: "Brand new reason" })
    ).toBe("Brand new reason");
  });
});

describe("describeErrorDetail", () => {
  it.each([
    ["Database error", m.skip_reason_detail_database()],
    ["Connection error", m.skip_reason_detail_connection()],
    ["Request timed out", m.skip_reason_detail_timeout()],
    ["HTTP 429 Too Many Requests", m.skip_reason_detail_http({ status: 429 })],
    ["TimeoutError while extracting pdf", "TimeoutError while extracting pdf"]
  ])("%s", (detail, expected) => {
    expect(describeErrorDetail(detail)).toBe(expected);
  });
});

describe("skipReasonKind", () => {
  it("is the code, and an error for anything unknown", () => {
    expect(skipReasonKind({ code: "no_text_layer" })).toBe("no_text_layer");
    expect(skipReasonKind({ reason: "No text layer" })).toBe("error");
    expect(skipReasonKind({ code: "brand_new" as SkipReasonCode })).toBe("error");
  });
});
