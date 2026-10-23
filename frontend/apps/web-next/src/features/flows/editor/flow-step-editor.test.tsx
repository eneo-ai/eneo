// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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

function renderEditor(
  flow: FlowPublic,
  overrides: { readOnly?: boolean; space?: ReturnType<typeof makeSpace> } = {}
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], overrides.space ?? makeSpace());
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
  it("shows the organisation's default step time limit and ceiling at the control", async () => {
    api.routes["GET /api/v1/flows/execution-limits/"] = () => ({
      body: { default_step_timeout_seconds: 900, max_step_timeout_seconds: 1800 }
    });
    renderEditor(makeFlow());
    const field = (await screen.findByLabelText(
      new RegExp(`^${messages.flow_step_editor_timeout}`)
    )) as HTMLInputElement;
    await waitFor(() => expect(field.placeholder).toBe("900"));
    expect(field.getAttribute("aria-valuemax") ?? field.max).toBe("1800");
    expect(screen.getByText(/1800/)).toBeTruthy();
    // A flow editor reads the Flows route, never the administrators' settings.
    expect(api.stub.calls.some((call) => call.path.startsWith("/api/v1/settings/"))).toBe(false);
  });

  it("keeps a working time limit control when the limits cannot be read", async () => {
    renderEditor(makeFlow());
    const field = (await screen.findByLabelText(
      new RegExp(`^${messages.flow_step_editor_timeout}`)
    )) as HTMLInputElement;
    await waitFor(() =>
      expect(api.stub.calls.some((call) => call.path === "/api/v1/flows/execution-limits/")).toBe(
        true
      )
    );
    expect(field.placeholder).toBe(messages.flow_step_editor_timeout_default);
    expect(field.getAttribute("aria-valuemax") ?? field.max).toBeFalsy();
  });

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

  it("reads long material in parts as one step setting, and explains what it costs", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved, container } = renderEditor(makeFlow());
    await nameField();
    const toggle = screen.getByRole("switch", { name: messages.flow_editor_tools_long_material });
    expect(screen.getByText(messages.flow_editor_tools_long_material_description)).toBeTruthy();
    fireEvent.click(toggle);
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()).toEqual([
      {
        expected_revision: 4,
        definition: {},
        step_edits: [
          { step_id: "step-1", changes: { input_config: { long_material: { mode: "digest" } } } }
        ]
      }
    ]);
  }, 20_000);

  it("shows what the step would send, its references named and no credential", async () => {
    routeBasics(
      makeAssistant({
        prompt: {
          id: "prompt-1",
          text: "Sammanfatta {{flow_input.diarienummer}} kort.",
          description: null
        } as never,
        completion_model_kwargs: { temperature: 0.2 }
      })
    );
    const { container } = renderEditor(
      makeFlow({
        metadata_json: {
          form_schema: { fields: [{ name: "diarienummer", label: "Diarienummer", type: "text" }] }
        }
      })
    );
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_preview_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_preview_title
    });
    expect(dialog.textContent).toContain("Diarienummer");
    expect(dialog.textContent).toContain("Haiku 4.5");
    expect(dialog.textContent).toContain("temperature: 0.2");
    await expectNoAxeViolations(container);
  }, 20_000);

  it("names a stored credential as stored in the preview, never its value", async () => {
    renderEditor(httpFlow({ mode: "bearer_token", token: { $secret: "stored" } }));
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_preview_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_preview_title
    });
    expect(dialog.textContent).toContain("https://api.example.org/a");
    expect(dialog.textContent).toContain(messages.flow_step_editor_secret_stored);
    expect(dialog.textContent).not.toContain("$secret");
  });

  it("proposes an output contract from an example answer, for the author to accept", async () => {
    api.routes[EDITOR] = () => ({ body: makeFlow({ draft_revision: 5 }) });
    const { onSaved, container } = renderEditor(
      makeFlow({ steps: [makeStep({ output_type: "json" })] })
    );
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_button })
    );
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_editor_tools_contract_example_title
    });
    fireEvent.change(screen.getByLabelText(/^Exempel på svar/), {
      target: { value: '{"beslut": "Bifall", "belopp": 4500}' }
    });
    expect(dialog.textContent).toContain("beslut");
    expect(dialog.textContent).toContain("Tal");
    await expectNoAxeViolations(container);
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_accept })
    );
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchBodies()[0]).toMatchObject({
      step_edits: [
        {
          step_id: "step-1",
          changes: {
            output_contract: {
              type: "object",
              properties: { beslut: { type: "string" }, belopp: { type: "number" } },
              required: ["beslut", "belopp"]
            }
          }
        }
      ]
    });
  }, 20_000);

  it("explains an example that gives no contract at the field", async () => {
    renderEditor(makeFlow({ steps: [makeStep({ output_type: "json" })] }));
    await nameField();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_button })
    );
    const field = await screen.findByLabelText(/^Exempel på svar/);
    fireEvent.change(field, { target: { value: "[1, 2]" } });
    expect(
      await screen.findByText(messages.flow_editor_tools_contract_example_problem_not_object)
    ).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
  });

  it("names classification levels from the space when the list is refused", async () => {
    api.routes["GET /api/v1/security-classifications/"] = () => ({
      status: 403,
      body: { message: "Forbidden", code: "forbidden" }
    });
    api.routes["POST /api/v1/flows/{id}/security-classification/preview"] = () => ({
      body: {
        steps: [
          {
            step_id: "step-1",
            step_order: 1,
            input_level: 1,
            reads: [],
            knowledge_level: null,
            external_source_level: null,
            model_level: 2,
            required_model_level: 1,
            qualifying_model_ids: ["model-1"],
            effective_output_level: 2,
            output_floor: 1,
            violation: null
          }
        ]
      }
    });
    const space = makeSpace({
      overrides: {
        security_classification: {
          id: "c-1",
          name: "Intern",
          description: null,
          security_level: 1
        },
        completion_models: [
          {
            id: "model-1",
            name: "snabb-modell",
            nickname: "Haiku 4.5",
            security_classification: {
              id: "c-2",
              name: "Känslig",
              description: null,
              security_level: 2
            }
          }
        ]
      }
    });
    renderEditor(makeFlow(), { space });
    await nameField();
    const facts = await screen.findByText(messages.flow_step_editor_classification_facts);
    const list = facts.closest("div")?.parentElement ?? document.body;
    await waitFor(() => expect(list.textContent).toContain("Känslig"));
    expect(list.textContent).toContain("Intern");
    expect(list.textContent).not.toContain("Nivå 2");
  });

  function attachFile(container: HTMLElement, name = "underlag.txt") {
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    fireEvent.change(input, {
      target: { files: [new File(["text"], name, { type: "text/plain" })] }
    });
  }

  const uploadable = makeAssistant({
    allowed_attachments: { accepted_file_types: [], limit: { max_files: 5, max_size: 10_000_000 } }
  } as never);

  it("releases a file uploaded in an edit that is cancelled", async () => {
    routeBasics(uploadable);
    api.routes["POST /api/v1/files/"] = () => ({
      body: { id: "file-new", name: "underlag.txt", size: 4, mimetype: "text/plain" }
    });
    api.routes["DELETE /api/v1/files/{id}/"] = () => ({ body: {} });
    const { container, onCancel } = renderEditor(makeFlow());
    await nameField();
    attachFile(container);
    expect(await screen.findByText("underlag.txt")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.flow_step_editor_discard })
    );
    await waitFor(() => expect(onCancel).toHaveBeenCalled());
    const deletes = api.stub.calls.filter((call) => call.method === "DELETE");
    expect(deletes).toEqual([
      expect.objectContaining({
        path: "/api/v1/files/{id}/",
        init: { params: { path: { id: "file-new" } } }
      })
    ]);
  });

  it("keeps a file the saved step uses when the editor closes", async () => {
    const withFile = makeAssistant({
      ...uploadable,
      attachments: [{ id: "file-new", name: "underlag.txt", size: 4 }]
    } as never);
    let saved = false;
    api.routes[ASSISTANT] = () => ({ body: saved ? withFile : uploadable });
    api.routes["POST /api/v1/files/"] = () => ({
      body: { id: "file-new", name: "underlag.txt", size: 4, mimetype: "text/plain" }
    });
    api.routes[EDITOR] = () => {
      saved = true;
      return { body: makeFlow({ draft_revision: 5 }) };
    };
    const { container, onSaved, unmount } = renderEditor(makeFlow());
    await nameField();
    attachFile(container);
    expect(await screen.findByText("underlag.txt")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_step_editor_save }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());

    unmount();
    expect(api.stub.calls.filter((call) => call.method === "DELETE")).toEqual([]);
  });

  it("offers no long material where the step does not let a model answer", async () => {
    renderEditor(makeFlow({ steps: [makeStep({ output_mode: "compose_text" })] }));
    await nameField();
    expect(
      screen.queryByRole("switch", { name: messages.flow_editor_tools_long_material })
    ).toBeNull();
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
            step_id: "step-1",
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

  it("releases a Word template uploaded in an edit that is closed without saving", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({ body: [] });
    api.routes["POST /api/v1/flows/{id}/template-files/"] = () => ({
      body: {
        id: "asset-new",
        flow_id: "flow-1",
        file_id: "file-9",
        name: "Ny.docx",
        checksum: "x",
        status: "ready",
        placeholders: []
      }
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      body: { asset_id: "asset-new", file_id: "file-9", file_name: "Ny.docx", placeholders: [] }
    });
    api.routes["DELETE /api/v1/flows/{id}/template-files/{file_id}/"] = () => ({ body: {} });
    const { container, unmount } = renderEditor(
      makeFlow({
        steps: [makeStep({ output_mode: "template_fill", output_type: "docx", output_config: {} })]
      })
    );
    await nameField();
    const input = await waitFor(() => {
      const found = container.querySelector<HTMLInputElement>('input[type="file"]');
      if (!found) throw new Error("no template input yet");
      return found;
    });
    fireEvent.change(input, {
      target: {
        files: [
          new File(["docx"], "Ny.docx", {
            type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          })
        ]
      }
    });
    await waitFor(() =>
      expect(
        api.stub.calls.some((call) => call.path === "/api/v1/flows/{id}/template-inspect/")
      ).toBe(true)
    );

    unmount();
    expect(
      api.stub.calls
        .filter((call) => call.method === "DELETE")
        .map((call) => call.init.params?.path)
    ).toEqual([{ id: "flow-1", file_id: "asset-new" }]);
  });

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
