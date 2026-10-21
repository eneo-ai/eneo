// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import type { FlowPublic } from "./step-types";
import { makeAssistant, makeFlow, makeStep } from "./testing/fixtures";

const api = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("./testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub: makeStub } = await import("./testing/fixtures");
  api.stub = makeStub(new Proxy({}, { get: (_target, key: string) => api.routes[key] }));
  return { browserApi: api.stub.client };
});

import { FlowStepEditor } from "./flow-step-editor";

const EDITOR = "PATCH /api/v1/flows/{id}/editor/";
const ASSISTANT = "GET /api/v1/flows/{id}/assistants/{assistant_id}/";

function routeBasics(assistant = makeAssistant()) {
  api.routes = {
    [ASSISTANT]: () => ({ body: assistant }),
    "GET /api/v1/spaces/": () => ({ body: { items: [] } }),
    "GET /api/v1/security-classifications/": () => ({
      body: { security_classifications: [], security_enabled: false }
    }),
    "GET /api/v1/flows/{id}/tool-options": () => ({
      body: { items: [], security_classifications_enabled: false }
    }),
    "POST /api/v1/flows/{id}/security-classification/preview": () => ({
      body: {
        steps: [
          {
            step_id: "step-1",
            step_order: 1,
            input_level: null,
            reads: [],
            knowledge_level: null,
            external_source_level: null,
            model_level: null,
            required_model_level: null,
            qualifying_model_ids: ["model-1", "model-2"],
            effective_output_level: null,
            output_floor: null,
            violation: null
          }
        ]
      }
    })
  };
}

function patchBodies() {
  return api.stub.calls
    .filter((call) => `${call.method} ${call.path}` === EDITOR)
    .map((call) => call.init.body);
}

function renderEditor(flow: FlowPublic, overrides: { readOnly?: boolean } = {}) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], makeSpace());
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  const view = renderInApp(
    <FlowStepEditor
      flow={flow}
      stepId="step-1"
      readOnly={overrides.readOnly ?? false}
      onSaved={onSaved}
      onCancel={onCancel}
    />,
    { queryClient }
  );
  return { ...view, onSaved, onCancel };
}

function httpFlow(auth: Record<string, unknown> = { mode: "none" }) {
  return makeFlow({
    steps: [
      makeStep({
        input_source: "http_get",
        output_mode: "compose_text",
        input_config: {
          url: "https://api.example.org/a",
          auth,
          timeout_seconds: 30,
          body: { mode: "none" },
          custom_headers: [],
          response_format: "text"
        }
      })
    ]
  });
}

async function nameField() {
  return (await screen.findByLabelText(/^Stegnamn/)) as HTMLInputElement;
}

beforeEach(() => routeBasics());
afterEach(() => {
  cleanup();
  api.stub.calls.length = 0;
});

describe("FlowStepEditor", () => {
  it("shows an AI step's task, input, result and control as labelled sections", async () => {
    const { container } = renderEditor(makeFlow());
    await nameField();
    for (const heading of [
      messages.flow_step_editor_ai_title,
      messages.flow_step_editor_input_title,
      messages.flow_step_editor_output_title,
      messages.flow_step_editor_control_title,
      messages.flow_step_editor_advanced_title
    ]) {
      expect(screen.getByRole("heading", { level: 3, name: heading })).toBeTruthy();
    }
    expect((screen.getByLabelText(/^Instruktion/) as HTMLTextAreaElement).value).toBe(
      "Sammanfatta ärendet."
    );
    await expectNoAxeViolations(container);
  }, 20_000);

  it("saves a renamed step as one fenced edit with only the name", async () => {
    const saved = makeFlow({
      draft_revision: 5,
      steps: [makeStep({ user_description: "Sammanfatta ärendet" })]
    });
    api.routes[EDITOR] = () => ({ body: saved });
    const { onSaved } = renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Sammanfatta ärendet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(patchBodies()).toEqual([
      {
        expected_revision: 4,
        definition: {},
        step_edits: [{ step_id: "step-1", changes: { user_description: "Sammanfatta ärendet" } }]
      }
    ]);
  });

  it("saves an instruction with the step assistant only, and reads the assistant back", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved } = renderEditor(makeFlow());
    await nameField();
    fireEvent.change(screen.getByLabelText(/^Instruktion/), {
      target: { value: "Sammanfatta i tre punkter." }
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()).toEqual([
      {
        expected_revision: 4,
        definition: {},
        assistants: [
          {
            assistant_id: "assistant-1",
            changes: { prompt: { text: "Sammanfatta i tre punkter.", description: null } }
          }
        ]
      }
    ]);
    const assistantReads = api.stub.calls.filter(
      (call) => `${call.method} ${call.path}` === ASSISTANT
    );
    expect(assistantReads.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the edits when the draft moved on, and saves them on the reloaded revision", async () => {
    let attempts = 0;
    api.routes[EDITOR] = () =>
      attempts++ === 0
        ? { status: 400, body: { message: "Stale", code: "stale_revision", eneo_error_code: 9000 } }
        : { body: makeFlow({ draft_revision: 9 }) };
    api.routes["GET /api/v1/flows/{id}/"] = () => ({ body: makeFlow({ draft_revision: 8 }) });
    const { onSaved } = renderEditor(makeFlow());
    fireEvent.change(await nameField(), { target: { value: "Nytt namn" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    expect(await screen.findByText(messages.flow_step_editor_stale_title)).toBeTruthy();
    expect((await nameField()).value).toBe("Nytt namn");
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_reload }));
    await waitFor(() =>
      expect(screen.queryByText(messages.flow_step_editor_stale_title)).toBeNull()
    );
    expect((await nameField()).value).toBe("Nytt namn");

    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[1]).toMatchObject({
      expected_revision: 8,
      step_edits: [{ step_id: "step-1", changes: { user_description: "Nytt namn" } }]
    });
  }, 20_000);

  it("shows a refusal at the field it names and moves focus there", async () => {
    const http = httpFlow();
    api.routes[EDITOR] = () => ({
      status: 400,
      body: {
        message: "Step 1: input_config.url is not valid",
        code: "typed_io_http_invalid_config",
        context: { field: "input_config.url", step_order: 1 },
        eneo_error_code: 9000
      }
    });
    renderEditor(http);
    const url = (await screen.findByLabelText(/^Adress att hämta från/)) as HTMLInputElement;
    fireEvent.change(url, { target: { value: "https://api.example.org/{{flow_input.id}}" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    expect(await screen.findByText(messages.flow_error_typed_io_http_invalid_config)).toBeTruthy();
    expect(document.activeElement).toBe(url);
    expect(screen.queryByText(/input_config\.url is not valid/)).toBeNull();
  });

  it("explains a missing name at the field instead of saving", async () => {
    renderEditor(makeFlow());
    const field = await nameField();
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    expect(await screen.findByText(messages.flow_step_editor_name_required)).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    expect(patchBodies()).toEqual([]);
  });

  it("shows a stored credential as saved, never as a value, and offers to replace it", async () => {
    const http = httpFlow({ mode: "bearer_token", token: { $secret: "stored" } });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { container, onSaved } = renderEditor(http);
    expect(await screen.findByText(messages.flow_step_editor_secret_stored)).toBeTruthy();
    expect(container.querySelector("input[type=password]")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Ersätt: Token" }));
    const token = container.querySelector("input[type=password]") as HTMLInputElement;
    expect(token.value).toBe("");
    fireEvent.change(token, { target: { value: "ny-hemlighet" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          changes: {
            input_config: { auth: { mode: "bearer_token", token: "ny-hemlighet" } }
          }
        }
      ]
    });
    await expectNoAxeViolations(container);
  }, 20_000);

  it("tests the HTTP call with the step's settings as they stand, credentials kept as stored", async () => {
    api.routes["POST /api/v1/flows/{id}/http-test"] = () => ({
      body: { success: true, status_code: 200, response_preview: '{"ok": true}' }
    });
    renderEditor(httpFlow({ mode: "bearer_token", token: { $secret: "stored" } }));
    fireEvent.click(await screen.findByRole("button", { name: messages.http_test_button }));

    expect(await screen.findByText(`${messages.http_test_success} (200)`)).toBeTruthy();
    const call = api.stub.calls.find((item) => item.path === "/api/v1/flows/{id}/http-test");
    expect(call?.init.body).toMatchObject({
      step_id: "step-1",
      direction: "input",
      method: "GET",
      config: { auth: { mode: "bearer_token", token: { $secret: "stored" } } }
    });
  }, 20_000);

  it("sets a tool step's arguments, one whole reference or a typed value each", async () => {
    api.routes["GET /api/v1/flows/{id}/tool-options"] = () => ({
      body: {
        security_classifications_enabled: false,
        items: [
          {
            mcp_server_id: "server-1",
            mcp_server_name: "Ärendesystem",
            mcp_server_security_level: null,
            tool_id: "tool-1",
            tool_name: "sok_arende",
            tool_description: "Söker ett ärende",
            input_schema: {
              type: "object",
              properties: { q: { type: "string" }, limit: { type: "integer" } },
              required: ["q"]
            },
            refusal: null
          }
        ]
      }
    });
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const tool = makeFlow({
      steps: [
        makeStep({
          input_source: "tool",
          output_mode: "compose_text",
          input_config: {
            tool: { mcp_server_id: "server-1", tool_id: "tool-1", arguments: { q: "{{datum}}" } }
          }
        })
      ]
    });
    const { container, onSaved } = renderEditor(tool);
    const limit = (await screen.findByLabelText(/^limit/)) as HTMLInputElement;
    expect((screen.getByLabelText(/^q/) as HTMLInputElement).value).toBe("{{datum}}");
    fireEvent.change(limit, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          changes: {
            input_config: {
              tool: {
                mcp_server_id: "server-1",
                tool_id: "tool-1",
                arguments: { q: "{{datum}}", limit: 5 }
              }
            }
          }
        }
      ]
    });
    await expectNoAxeViolations(container);
  }, 20_000);

  it("binds a Word template's fields to values of the run", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [
        {
          id: "asset-1",
          flow_id: "flow-1",
          file_id: "file-1",
          name: "Beslut.docx",
          checksum: "abc",
          status: "ready",
          placeholders: ["namn"]
        }
      ]
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      body: {
        asset_id: "asset-1",
        file_id: "file-1",
        file_name: "Beslut.docx",
        placeholders: [{ name: "namn", label: "Namn", kind: "text", location: "body" }]
      }
    });
    const template = makeFlow({
      metadata_json: { form_schema: { fields: [{ name: "namn", label: "Namn", type: "text" }] } },
      steps: [
        makeStep({
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_asset_id: "asset-1",
            template_name: "Beslut.docx",
            placeholders: ["namn"],
            bindings: {}
          }
        })
      ]
    });
    const { container } = renderEditor(template);
    expect(await screen.findByText(messages.flow_step_editor_template_field_missing)).toBeTruthy();
    expect(screen.getByText("0 av 1 fält är kopplade.")).toBeTruthy();
    await expectNoAxeViolations(container);
  }, 20_000);

  it("shows a read-only step as text, without inputs", async () => {
    const { container } = renderEditor(makeFlow(), { readOnly: true });
    expect(await screen.findByText("Sammanfatta ärendet.")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: messages.flow_step_editor_save })).toBeNull();
    // The result's mode is told in the header and in the list of settings.
    expect(screen.getByText(messages.flow_step_output_mode)).toBeTruthy();
    expect(screen.getAllByText(messages.flow_output_mode_pass_through)).toHaveLength(2);
    await expectNoAxeViolations(container);
  }, 20_000);
});
