import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

function readMessages(locale: "sv" | "en") {
  const filePath = path.resolve(process.cwd(), `messages/${locale}.json`);
  return JSON.parse(readFileSync(filePath, "utf-8")) as Record<string, string>;
}

describe("flow run evidence copy", () => {
  it("distinguishes credential masking from content removal in Swedish", () => {
    const messages = readMessages("sv");

    expect(messages.flow_run_evidence_redacted).toBe("Åtkomstuppgifter maskerade");
    expect(messages.flow_run_debug_tools).toBe("Tekniska verktyg");
    expect(messages.flow_run_evidence_trace_id).toBe("Spår-ID");
    expect(messages.flow_run_download_evidence_export).toBe("Ladda ner bevisunderlag");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("API-nycklar");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("bearer-tokens");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("personuppgifter");
  });

  it("distinguishes credential masking from content removal in English", () => {
    const messages = readMessages("en");

    expect(messages.flow_run_evidence_redacted).toBe("Credentials masked");
    expect(messages.flow_run_debug_tools).toBe("Technical tools");
    expect(messages.flow_run_evidence_trace_id).toBe("Trace ID");
    expect(messages.flow_run_download_evidence_export).toBe("Download evidence file");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("API keys");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("bearer tokens");
    expect(messages.flow_run_evidence_redacted_tooltip).toContain("personal data");
  });
});
