import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

function readMessages(locale: "sv" | "en") {
  const filePath = path.resolve(process.cwd(), `messages/${locale}.json`);
  return JSON.parse(readFileSync(filePath, "utf-8")) as Record<string, string>;
}

describe("flow run evidence copy", () => {
  it("uses clearer export-safe terminology in Swedish", () => {
    const messages = readMessages("sv");

    expect(messages.flow_run_evidence_redacted).toBe("Säker för export");
    expect(messages.flow_run_debug_tools).toBe("Tekniska verktyg");
    expect(messages.flow_run_evidence_trace_id).toBe("Spår-ID");
    expect(messages.flow_run_download_evidence_export).toBe("Ladda ner bevisunderlag");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("API-nycklar");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("bearer-tokens");
  });

  it("uses clearer export-safe terminology in English", () => {
    const messages = readMessages("en");

    expect(messages.flow_run_evidence_redacted).toBe("Export-safe");
    expect(messages.flow_run_debug_tools).toBe("Technical tools");
    expect(messages.flow_run_evidence_trace_id).toBe("Trace ID");
    expect(messages.flow_run_download_evidence_export).toBe("Download evidence file");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("API keys");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("bearer tokens");
  });
});
