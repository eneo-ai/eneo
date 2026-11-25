// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

describe("an argument's field", () => {
  const SQL = [
    "SELECT    x.pump,",
    "CASE WHEN MONTH(b.Readdatetime) >= 10 THEN YEAR(b.Readdatetime)",
    "ELSE YEAR(b.Readdatetime) - 1 END AS season_year",
    "FROM readings b JOIN pumps x ON x.id = b.pump_id",
    "GROUP BY x.pump ORDER BY x.pump, manad"
  ].join("\n");

  function renderArguments(args: Record<string, unknown> = {}) {
    api.routes["GET /api/v1/flows/{id}/tool-options"] = () => ({
      body: {
        items: [
          {
            mcp_server_id: "s-1",
            mcp_server_name: "Databas",
            mcp_server_security_level: null,
            tool_id: "query",
            tool_name: "Fråga",
            tool_description: null,
            refusal: null,
            input_schema: {
              properties: {
                sql: { type: "string" },
                values: { type: "array", items: { type: "number" } },
                count: { type: "integer" },
                active: { type: "boolean" },
                note: {}
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
            { name: "namn", label: "Namn", type: "text" },
            { name: "deltagare", label: "Deltagare", type: "list" },
            { name: "antal", label: "Antal", type: "number" }
          ]
        }
      },
      steps: [makeStep(1)]
    });
    const onChange = vi.fn();
    renderInApp(
      <ToolFields
        flowId={flow.id}
        tool={{ mcp_server_id: "s-1", tool_id: "query", arguments: args }}
        onChange={onChange}
        groups={variableGroups({ flow, stepOrder: 1 })}
      />
    );
    const stored = () => (onChange.mock.lastCall?.[0] as { arguments: unknown }).arguments;
    return { stored };
  }

  it("keeps the line breaks of a text it is given", async () => {
    const { stored } = renderArguments();
    const sql = await screen.findByRole("textbox", { name: /^sql/ });
    fireEvent.change(sql, { target: { value: SQL } });
    expect(stored()).toEqual({ sql: SQL });
    // An argument without a type takes text the same way.
    const note = screen.getByRole("textbox", { name: /^note/ });
    expect(note).toBeInstanceOf(HTMLTextAreaElement);
    fireEvent.change(note, { target: { value: SQL } });
    expect(stored()).toEqual({ note: SQL });
  });

  it("shows a long text on many lines, one line while it is short", async () => {
    const long = Array.from({ length: 60 }, (_, line) => `${SQL} -- ${line}`)
      .join("\n")
      .slice(0, 3000);
    renderArguments({ sql: long });
    const sql = await screen.findByRole("textbox", { name: /^sql/ });
    expect(sql).toBeInstanceOf(HTMLTextAreaElement);
    expect((sql as HTMLTextAreaElement).value).toBe(long);
    // Where the browser cannot fit the field to its text, it still opens on
    // the lines it has, up to the same cap the field scrolls past.
    expect(sql.getAttribute("rows")).toBe("15");
    cleanup();

    renderArguments({ sql: "SELECT 1" });
    expect((await screen.findByRole("textbox", { name: /^sql/ })).getAttribute("rows")).toBe("1");
  });

  it("still reads a whole reference with spaces or line breaks around it, and says what is wrong as before", async () => {
    renderArguments({
      sql: "\n  {{flow_input.namn}}\n",
      values: " {{flow_input.deltagare}}\n",
      count: "{{flow_input.antal}} st",
      active: "kanske"
    });
    const sql = await screen.findByRole("textbox", { name: /^sql/ });
    expect(sql.getAttribute("aria-invalid")).not.toBe("true");
    expect(screen.getByRole("textbox", { name: /^values/ }).getAttribute("aria-invalid")).toBe(
      "true"
    );
    expect(
      screen.getAllByText(
        "Formulärfältet ”Deltagare” passar inte här: verktyget vill ha typen array<number>. Välj ett annat värde."
      ).length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(messages.flow_step_editor_tool_argument_composed).length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        messages.flow_step_editor_tool_argument_not_json.replace("{type}", "boolean")
      ).length
    ).toBeGreaterThan(0);
    cleanup();

    // The growing field says what is wrong the same way.
    renderArguments({ sql: "SELECT *\nWHERE namn = {{flow_input.namn}}" });
    const mixed = await screen.findByRole("textbox", { name: /^sql/ });
    expect(mixed).toBeInstanceOf(HTMLTextAreaElement);
    expect(mixed.getAttribute("aria-invalid")).toBe("true");
    expect(
      screen.getAllByText(messages.flow_step_editor_tool_argument_composed).length
    ).toBeGreaterThan(0);
  });

  it("keeps a number and a true-or-false value on one line, stored as their type", async () => {
    const { stored } = renderArguments();
    const count = await screen.findByRole("textbox", { name: /^count/ });
    const active = screen.getByRole("textbox", { name: /^active/ });
    expect(count).toBeInstanceOf(HTMLInputElement);
    expect(active).toBeInstanceOf(HTMLInputElement);
    fireEvent.change(count, { target: { value: "42" } });
    expect(stored()).toEqual({ count: 42 });
    fireEvent.change(active, { target: { value: "true" } });
    expect(stored()).toEqual({ active: true });
  });
});
