// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { makeFlow, makeStep } from "../flow-fixtures";
import { variableGroups } from "./step-variables";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("./testing/fixtures");
  return {
    browserApi: apiStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] })).client
  };
});

import { ToolFields } from "./step-tool-fields";

afterEach(() => {
  cleanup();
  api.routes = {};
});

it("says at the argument when a form field's value cannot be the type the tool takes", async () => {
  api.routes["GET /api/v1/flows/{id}/tool-options"] = () => ({
    body: {
      items: [
        {
          mcp_server_id: "s-1",
          mcp_server_name: "Räknare",
          mcp_server_security_level: null,
          tool_id: "sum",
          tool_name: "Summera",
          tool_description: null,
          refusal: null,
          input_schema: {
            properties: {
              values: { type: "array", items: { type: "number" } },
              count: { type: "integer" }
            }
          }
        }
      ]
    }
  });
  const flow = makeFlow({
    metadata_json: {
      form_schema: {
        fields: [
          { name: "deltagare", label: "Deltagare", type: "list" },
          { name: "antal", label: "Antal", type: "number" }
        ]
      }
    },
    steps: [makeStep(1)]
  });
  renderInApp(
    <ToolFields
      flowId={flow.id}
      tool={{
        mcp_server_id: "s-1",
        tool_id: "sum",
        arguments: { values: "{{flow_input.deltagare}}", count: "{{flow_input.antal}}" }
      }}
      onChange={() => {}}
      groups={variableGroups({ flow, stepOrder: 1 })}
    />
  );
  const values = await screen.findByRole("textbox", { name: /^values/ });
  expect(values.getAttribute("aria-invalid")).toBe("true");
  expect(
    screen.getAllByText(
      "Formulärfältet ”Deltagare” passar inte här: verktyget vill ha typen array<number>. Välj ett annat värde."
    ).length
  ).toBeGreaterThan(0);
  expect(screen.getByRole("textbox", { name: /^count/ }).getAttribute("aria-invalid")).not.toBe(
    "true"
  );
});

it("says a personal space has no tools for a flow, instead of asking an administrator", async () => {
  api.routes["GET /api/v1/flows/{id}/tool-options"] = () => ({
    body: { items: [], security_classifications_enabled: false }
  });
  renderInApp(<ToolFields flowId="flow-1" tool={null} onChange={() => {}} groups={[]} personal />);
  expect(await screen.findByText(messages.flow_step_editor_tools_personal)).toBeTruthy();
  expect(screen.queryByText(messages.flow_step_editor_tools_none)).toBeNull();
});
