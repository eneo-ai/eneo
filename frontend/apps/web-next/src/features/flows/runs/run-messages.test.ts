import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { testTranslator } from "@/test/i18n";
import { runErrorText } from "./run-messages";

const t = testTranslator();

describe("runErrorText", () => {
  it("names the service and its status when an HTTP step was answered with an error", () => {
    const http = (status: number) =>
      runErrorText(
        {
          code: "typed_io_http_non_success",
          details: { http_status: status, http_host: "api.example.org" }
        },
        t
      );
    expect(http(401)).toBe(
      "Tjänsten api.example.org nekade anropet (status 401). Kontrollera inloggningen i steget."
    );
    expect(http(403)).toContain("nekade anropet (status 403)");
    expect(http(404)).toBe(
      "Adressen finns inte hos api.example.org (status 404). Kontrollera adressen i steget."
    );
    expect(http(500)).toBe(
      "Tjänsten api.example.org svarade med ett fel (status 500). Be en flödesredigerare kontrollera tjänsten."
    );
    // A stored error from before the facts existed keeps the code's own sentence.
    expect(runErrorText({ code: "typed_io_http_non_success", details: null }, t)).toBe(
      messages.flow_error_typed_io_http_non_success
    );
  });

  it("says why a step's tool was refused and, when the space turned it off, who can turn it on", () => {
    const refused = (refusal: string) =>
      runErrorText(
        { code: "typed_io_tool_not_allowed", details: { tool_refusal: refusal } } as Parameters<
          typeof runErrorText
        >[0],
        t
      );
    expect(refused("tool_switched_off_in_space")).toBe(
      `${messages.flow_step_editor_tool_refusal_tool_switched_off_in_space} ${messages.flow_run_tool_refused_ask_space_admin}`
    );
    expect(refused("server_not_in_space")).toBe(
      `${messages.flow_step_editor_tool_refusal_server_not_in_space} ${messages.flow_run_tool_refused_ask_space_admin}`
    );
    expect(refused("server_disabled")).toBe(messages.flow_step_editor_tool_refusal_server_disabled);
    expect(runErrorText({ code: "typed_io_tool_not_allowed", details: null }, t)).toBe(
      messages.flow_error_typed_io_tool_not_allowed
    );
  });

  it("does not tell a person to simplify their text when the Word runtime refused the template", () => {
    const text = runErrorText(
      {
        code: "typed_io_template_render_failed",
        details: { template_fill: { reason: "render_refused" } }
      },
      t
    );
    expect(text).toBe(messages.flow_run_template_fill_render_refused);
    expect(text).not.toMatch(/Förenkla/);
  });
});
