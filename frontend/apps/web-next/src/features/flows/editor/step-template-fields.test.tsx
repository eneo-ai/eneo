// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import { makeFlow, makeStep } from "../flow-fixtures";
import { stepConfigOf } from "./step-types";
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

import { suggestedBindings, TemplateFillFields } from "./step-template-fields";

afterEach(() => {
  cleanup();
  api.routes = {};
});

const flow = makeFlow({
  metadata_json: {
    form_schema: {
      fields: [
        { name: "namn", label: "Namn", type: "text" },
        { name: "deltagare", label: "Deltagare", type: "list" }
      ]
    }
  },
  steps: [makeStep(1, { user_description: "Beslut" }), makeStep(2)]
});
const groups = variableGroups({ flow, stepOrder: 2 });

describe("suggestedBindings", () => {
  it("binds placeholders named like a form field, an earlier step or today's date", () => {
    // A list holds several values: a Word field named like it is left for the author.
    expect(suggestedBindings(["Namn", "beslut", "Datum", "Okänt", "Deltagare"], groups)).toEqual({
      Namn: "{{flow_input.namn}}",
      beslut: "{{step_1.output.text}}",
      Datum: "{{datum}}"
    });
  });
});

describe("TemplateFillFields", () => {
  it("starts at the upload with the guide open, and offers another template only once one is chosen", async () => {
    const renderUnchosen = () =>
      renderInApp(
        <TemplateFillFields
          flow={flow}
          stepOrder={2}
          draft={{
            ...stepConfigOf(makeStep(2)),
            output_mode: "template_fill",
            output_type: "docx"
          }}
          onChange={() => {}}
          groups={groups}
        />
      );
    const guideOpen = () =>
      screen
        .getByRole("button", { name: messages.flow_step_editor_template_guide_title })
        .getAttribute("aria-expanded");
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({ body: [] });
    renderUnchosen();
    expect(
      await screen.findByRole("button", { name: messages.flow_step_editor_template_upload_first })
    ).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: messages.flow_step_editor_template })).toBeNull();
    expect(guideOpen()).toBe("true");
    cleanup();

    // The flow has a template, but this step has none yet: "another" would not fit.
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [{ id: "asset-1", flow_id: "flow-1", file_id: "file-1", name: "Beslut.docx" }]
    });
    renderUnchosen();
    expect(
      await screen.findByRole("combobox", { name: messages.flow_step_editor_template })
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: messages.flow_step_editor_template_upload_first })
    ).toBeTruthy();
    expect(guideOpen()).toBe("false");
  });

  it("counts only fields set to a value the flow has and names the rest at the field", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [
        {
          id: "asset-1",
          flow_id: "flow-1",
          file_id: "file-1",
          name: "Beslut.docx",
          checksum: "abc",
          status: "ready",
          placeholders: ["namn", "datum", "beslut"]
        }
      ]
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({
      body: {
        asset_id: "asset-1",
        file_id: "file-1",
        file_name: "Beslut.docx",
        placeholders: [
          { name: "namn", label: "Namn", kind: "text", location: "body" },
          { name: "datum", label: "Datum", kind: "text", location: "body" },
          { name: "beslut", label: "Beslut", kind: "text", location: "body" }
        ]
      }
    });
    renderInApp(
      <TemplateFillFields
        flow={flow}
        stepOrder={2}
        draft={{
          ...stepConfigOf(makeStep(2)),
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_asset_id: "asset-1",
            template_name: "Beslut.docx",
            placeholders: ["namn", "datum", "beslut"],
            bindings: { namn: "{{step_9.output.text}}", datum: "{{datum}}" }
          }
        }}
        onChange={() => {}}
        groups={groups}
      />
    );
    // The reference to a step the flow no longer has is not counted as done.
    expect(
      await screen.findByText(
        "1 av 3 fält är klara. Välj vad som ska stå i resten, eller Lämna tomt."
      )
    ).toBeTruthy();
    // Once, at the field: the status Astryx also reads out is not counted.
    expect(
      screen.getByText(messages.flow_step_editor_template_field_unknown, {
        ignore: "script, style, [data-astryx-live-region]"
      })
    ).toBeTruthy();
    // Each field tells assistive technology what fills it, or that nothing does yet.
    expect(screen.getByRole("combobox", { name: "Beslut" }).textContent).toContain(
      messages.flow_step_editor_template_field_unbound
    );
    expect(screen.getByRole("combobox", { name: "Datum" }).textContent).toContain("Dagens datum");
    // The reference to a step that is gone is not shown as code.
    expect(screen.getByRole("combobox", { name: "Namn" }).textContent).toContain(
      messages.flow_step_editor_template_field_gone
    );
    expect(screen.queryByText(/\{\{/)).toBeNull();
    // The count is a status, read out when it changes.
    expect(screen.getByText(/^1 av 3 fält/).closest('[role="status"]')).toBeTruthy();
    // A field takes one value: the previous step's answer is offered by its step instead.
    fireEvent.click(screen.getByRole("combobox", { name: "Beslut" }));
    const options = within(await screen.findByRole("listbox", { name: "Beslut" }));
    expect(options.getByRole("option", { name: /^Dagens datum/ })).toBeTruthy();
    expect(
      options.queryByRole("option", { name: messages.flow_step_editor_variable_previous_step })
    ).toBeNull();
  });
});

const inspected = {
  asset_id: "asset-1",
  file_id: "file-1",
  file_name: "Beslut.docx",
  placeholders: ["datum", "namn", "okant"].map((name) => ({
    name,
    label: name,
    kind: "text",
    location: "body"
  }))
};
const asset = (id: string, name: string) => ({
  id,
  flow_id: "flow-1",
  file_id: `file-${id}`,
  name,
  checksum: "abc",
  status: "ready",
  placeholders: ["datum", "namn", "okant"]
});

function renderTemplate(outputConfig: Record<string, unknown> = {}) {
  const onChange = vi.fn();
  const view = renderInApp(
    <TemplateFillFields
      flow={flow}
      stepOrder={2}
      draft={{
        ...stepConfigOf(makeStep(2)),
        output_mode: "template_fill",
        output_type: "docx",
        output_config: outputConfig
      }}
      onChange={onChange}
      groups={groups}
    />
  );
  return { ...view, onChange };
}

describe("TemplateFillFields choices", () => {
  it("binds the fields named like a value of the flow when a template is chosen, and keeps what the author set", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [asset("asset-0", "Gammal.docx"), asset("asset-1", "Beslut.docx")]
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({ body: inspected });
    const choose = async () => {
      fireEvent.click(
        await screen.findByRole("combobox", { name: messages.flow_step_editor_template })
      );
      fireEvent.click(await screen.findByRole("option", { name: /^Beslut\.docx/ }));
    };

    const first = renderTemplate();
    await choose();
    await waitFor(() => expect(first.onChange).toHaveBeenCalled());
    expect(first.onChange.mock.lastCall?.[0]).toMatchObject({
      template_asset_id: "asset-1",
      bindings: { datum: "{{datum}}", namn: "{{flow_input.namn}}" }
    });
    expect(Object.keys(first.onChange.mock.lastCall?.[0].bindings)).toEqual(["datum", "namn"]);
    cleanup();

    // "Lämna tomt" is the author's choice: the suggestion does not overwrite it.
    const second = renderTemplate({
      template_asset_id: "asset-0",
      template_name: "Gammal.docx",
      placeholders: ["datum", "namn", "okant"],
      bindings: { datum: "" }
    });
    await choose();
    await waitFor(() => expect(second.onChange).toHaveBeenCalled());
    expect(second.onChange.mock.lastCall?.[0].bindings).toEqual({
      datum: "",
      namn: "{{flow_input.namn}}"
    });
  });

  it("refuses a file that is not .docx beside its name, and clears the name once a template is up", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({ body: [] });
    api.routes["POST /api/v1/flows/{id}/template-files/"] = () => ({
      body: asset("asset-1", "Beslut.docx")
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({ body: inspected });
    const { container, onChange } = renderTemplate();
    await screen.findByRole("button", { name: messages.flow_step_editor_template_upload_first });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;

    // The browser's file type passes the picker's filter; the name is not .docx.
    fireEvent.change(input, {
      target: {
        files: [
          new File(["x"], "Anteckning.doc", {
            type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          })
        ]
      }
    });
    expect(
      await screen.findAllByText(messages.flow_error_flow_template_unsupported_extension)
    ).not.toHaveLength(0);
    expect(screen.getByText("Anteckning.doc")).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(input, {
      target: {
        files: [
          new File(["docx"], "Beslut.docx", {
            type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          })
        ]
      }
    });
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(onChange.mock.lastCall?.[0]).toMatchObject({ template_asset_id: "asset-1" });
    await waitFor(() => expect(screen.queryByText("Beslut.docx")).toBeNull());
    expect(screen.queryByText("Anteckning.doc")).toBeNull();
    // Gone from the field; the announcement Astryx already made is not part of it.
    expect(
      screen.queryAllByText(messages.flow_error_flow_template_unsupported_extension, {
        ignore: "script, style, [data-astryx-live-region]"
      })
    ).toHaveLength(0);
  });

  it("shows a binding written otherwise than the picker writes it as the value it reads", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [asset("asset-1", "Beslut.docx")]
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({ body: inspected });
    renderTemplate({
      template_asset_id: "asset-1",
      template_name: "Beslut.docx",
      placeholders: ["datum", "namn", "okant"],
      bindings: { datum: "{{ datum }}", namn: "{{föregående_steg}}", okant: "" }
    });
    expect(await screen.findByText("Alla 3 fält är klara.")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "datum" }).textContent).toContain("Dagens datum");
    expect(screen.getByRole("combobox", { name: "namn" }).textContent).toContain("Beslut");
    expect(screen.queryByText(messages.flow_step_editor_template_field_unknown)).toBeNull();
    expect(screen.queryByText(/\{\{/)).toBeNull();
  });

  it("says a list cannot fill a Word field, and does not offer one", async () => {
    api.routes["GET /api/v1/flows/{id}/template-files/"] = () => ({
      body: [asset("asset-1", "Beslut.docx")]
    });
    api.routes["GET /api/v1/flows/{id}/template-inspect/"] = () => ({ body: inspected });
    renderTemplate({
      template_asset_id: "asset-1",
      template_name: "Beslut.docx",
      placeholders: ["datum", "namn", "okant"],
      bindings: { datum: "{{datum}}", namn: "{{flow_input.deltagare}}", okant: "" }
    });
    expect(await screen.findByText(messages.flow_step_editor_template_field_list)).toBeTruthy();
    expect(screen.getByText(/^2 av 3 fält är klara\./)).toBeTruthy();
    const namn = screen.getByRole("combobox", { name: "namn" });
    expect(namn.textContent).toContain("Deltagare");
    expect(screen.queryByText(messages.flow_step_editor_template_field_unknown)).toBeNull();
    fireEvent.click(screen.getByRole("combobox", { name: "okant" }));
    const options = within(await screen.findByRole("listbox", { name: "okant" }));
    expect(options.getByRole("option", { name: "Namn" })).toBeTruthy();
    expect(options.queryByRole("option", { name: "Deltagare" })).toBeNull();
  });
});
