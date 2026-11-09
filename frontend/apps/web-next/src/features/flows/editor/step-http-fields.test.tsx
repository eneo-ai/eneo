// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import type { FieldProblems } from "./field-problems";
import { defaultHttpConfig, type HttpConfig } from "./step-configs";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("./testing/fixtures");
  return {
    browserApi: apiStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] })).client
  };
});

import { HttpFields, sampleTestVariables } from "./step-http-fields";

afterEach(() => {
  cleanup();
  api.routes = {};
});

function renderFields(
  config: Partial<HttpConfig>,
  direction: "input" | "output" = "input",
  problems: FieldProblems = {}
) {
  return renderInApp(
    <HttpFields
      formId="form"
      problems={problems}
      flowId="flow-1"
      stepId="step-1"
      direction={direction}
      config={{ ...defaultHttpConfig(direction), ...config }}
      onChange={() => {}}
      groups={[]}
    />
  );
}

const moreSettings = () =>
  screen.getByRole("button", { name: new RegExp(messages.flow_step_editor_http_more_title) });

describe("HttpFields", () => {
  it("folds headers and the time limit while the defaults hold, and opens on a setting in use", () => {
    renderFields({ url: "https://api.example.org/a" });
    expect(moreSettings().getAttribute("aria-expanded")).toBe("false");
    cleanup();

    renderFields({
      url: "https://api.example.org/a",
      custom_headers: [{ name: "X-Kommun", value: "Sundsvall", secret: false }]
    });
    expect(moreSettings().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByDisplayValue("X-Kommun")).toBeTruthy();
  });

  it("counts only headers with a name, and says a row without one is not sent", () => {
    renderFields({
      url: "https://api.example.org/a",
      custom_headers: [
        { name: "", value: "", secret: false },
        { name: " ", value: "Sundsvall", secret: false }
      ]
    });
    expect(moreSettings().getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(moreSettings());
    // Only the row with a value and no name gets the hint.
    expect(screen.getAllByText(messages.flow_step_editor_http_header_name_missing)).toHaveLength(1);
  });

  it("shows a refused save at the part it is about, and opens the fold for a setting in it", () => {
    renderFields(
      {
        url: "https://api.example.org/a",
        body: { mode: "json_template", template: "{" }
      },
      "output",
      {
        "output_config.http.body": "Mallen är inte giltig JSON",
        "output_config.http.more": "Väntetiden är för lång"
      }
    );
    const template = screen.getByRole("textbox", {
      name: new RegExp(messages.flow_step_editor_http_body_template)
    });
    expect(template.getAttribute("aria-invalid")).toBe("true");
    const address = screen.getByRole("textbox", {
      name: new RegExp(messages.flow_step_editor_http_url_post)
    });
    expect(address.getAttribute("aria-invalid")).not.toBe("true");
    expect(moreSettings().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Väntetiden är för lång")).toBeTruthy();
  });

  it("fills the test values with one empty value per reference the call reads", () => {
    expect(
      JSON.parse(
        sampleTestVariables({
          ...defaultHttpConfig("output"),
          url: "{{base_url}}/cases/{{step_1.output.id}}",
          body: { mode: "json_template", template: '{"text": "{{ step_1.output.text }}"}' }
        })
      )
    ).toEqual({ base_url: "", step_1: { output: { id: "", text: "" } } });
    expect(sampleTestVariables(defaultHttpConfig("output"))).toBe("{}");
  });

  it("refuses at the address when a credential would go to a plain http:// or variable host", () => {
    renderFields({
      url: "http://api.example.org/a",
      auth: { mode: "bearer_token", token: "" }
    });
    expect(screen.getByText(messages.flow_step_editor_http_credentials_need_https)).toBeTruthy();
    cleanup();

    renderFields({ url: "{{base_url}}/a", auth: { mode: "bearer_token", token: "" } });
    expect(screen.getByText(messages.flow_step_editor_http_credentials_need_https)).toBeTruthy();
    cleanup();

    renderFields({
      url: "https://api.example.org/{{case_id}}",
      auth: { mode: "bearer_token", token: "" }
    });
    expect(screen.queryByText(messages.flow_step_editor_http_credentials_need_https)).toBeNull();
  });

  it("says what a refused sign-in means when the connection test gets 401", async () => {
    api.routes["POST /api/v1/flows/{id}/http-test"] = () => ({
      body: { success: false, status_code: 401, error_code: "HTTP_STATUS_ERROR" }
    });
    renderFields({ url: "https://api.example.org/a" });
    fireEvent.click(screen.getByRole("button", { name: messages.http_test_button }));

    expect(
      await screen.findByText(messages.http_test_status_auth.replace("{status}", "401"))
    ).toBeTruthy();
    expect(screen.getByText(messages.http_test_failed_prefix)).toBeTruthy();
  });

  it("tells the author that testing a delivery sends a real call to the receiver", () => {
    renderFields({ url: "https://api.example.org/a" }, "output");
    expect(screen.getByText(messages.http_test_desc_output)).toBeTruthy();
  });
});
