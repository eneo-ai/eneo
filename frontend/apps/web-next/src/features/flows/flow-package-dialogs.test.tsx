// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { makeFlow, makeStep } from "./flow-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }));
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  PUT: vi.fn(),
  DELETE: vi.fn()
}));
const saved = vi.hoisted(() => ({ saveBlob: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));
vi.mock("@/features/files/signed-file-url", () => saved);
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});

import { FlowPackageExportDialog } from "./flow-package-export-dialog";
import { FlowPackageImportDialog } from "./flow-package-import-dialog";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

describe("FlowPackageExportDialog", () => {
  it("exports the flow and asks before saving a package without its MCP connections", async () => {
    const blob = new Blob(["zip"]);
    api.POST.mockResolvedValue({
      data: blob,
      response: new Response(null, {
        status: 200,
        headers: {
          "content-disposition": 'attachment; filename="local.brev-1.0.0.eneopkg"',
          "eneo-package-omitted-mcp-assistant-count": "2"
        }
      })
    });
    const flow = makeFlow({ name: "Brev för nämnden" });
    const { container } = renderInApp(
      <FlowPackageExportDialog flow={flow} open onOpenChange={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Avancerat" }));
    expect((screen.getByRole("textbox", { name: /Paket-ID/ }) as HTMLInputElement).value).toBe(
      "local.brev-for-namnden"
    );
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));

    expect(await screen.findByText("MCP-kopplingar ingår inte")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/{id}/package-exports/", {
      params: { path: { id: "flow-1" } },
      body: {
        package_id: "local.brev-for-namnden",
        package_version: "1.0.0",
        name: "Brev för nämnden",
        description: "Sammanfattar och besvarar brev.",
        include_templates: true
      },
      parseAs: "blob"
    });
    expect(saved.saveBlob).not.toHaveBeenCalled();
    const save = screen.getByRole("button", { name: "Spara paket" });
    fireEvent.click(save);
    expect(
      await screen.findByText("Bekräfta först att MCP-kopplingarna inte följer med.")
    ).toBeTruthy();
    expect(saved.saveBlob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Jag förstår/ }));
    fireEvent.click(save);
    expect(saved.saveBlob).toHaveBeenCalledWith(blob, "local.brev-1.0.0.eneopkg");
  }, 20_000);

  it("says in words why the export was refused and which step it is about", async () => {
    api.POST.mockResolvedValue({
      error: {
        message: "Not portable",
        code: "flow_package_export_step_config_not_portable",
        context: { step_order: 2, config_field: "output_config" }
      },
      response: json(400, {})
    });
    renderInApp(
      <FlowPackageExportDialog
        flow={makeFlow({ steps: [makeStep(1), makeStep(2)] })}
        open
        onOpenChange={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));
    expect(await screen.findByText(/Det gäller utdatainställningarna i steg 2\./)).toBeTruthy();
    // The refusal also covers steps that are not HTTP calls: removing the step is not the fix there.
    expect(screen.queryByText(/Ta bort steget/)).toBeNull();
  });
});

describe("FlowPackageImportDialog", () => {
  const plan = {
    can_install_as_draft: true,
    can_publish_after_import: true,
    content_checksum: "abc",
    dependency_resolutions: [
      {
        kind: "model",
        slot_ref: { kind: "model", slot: "writer", label: "Skrivmodell" },
        status: "requires_human_confirmation",
        required: true,
        selection_required_for_install: true,
        install_blocks: true,
        publish_blocks: true,
        auto_select_allowed: false,
        suggestions: [{ local_kind: "completion_model", local_id: "m-1", label: "Modell A" }],
        total_candidate_count: 1,
        eligible_candidate_count: 1,
        model_kind: "completion_model",
        matching_preferences: {},
        policy_status: "allowed",
        used_by_steps: ["Skriv svar"]
      }
    ],
    kind: "flow",
    omissions: [],
    package_id: "local.brev",
    package_summary: {
      name: "Brev",
      description: "Besvarar brev.",
      requirements_by_kind: {},
      requirements_count: 1,
      spec_hash: "h",
      steps_count: 2
    },
    package_version: "1.0.0",
    payload_schema: "flow/v1",
    target_state: { audio_transcription_required: false, default_transcription_model_id: null },
    transcription_model_available: true
  };

  const BLOCKED = "Paketet kan inte importeras förrän dessa punkter är lösta.";
  const progress = (selected: number) => `${selected} av 1 obligatoriska val är gjorda.`;

  function renderImport(onOpenChange = vi.fn()) {
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
    return renderInApp(<FlowPackageImportDialog open onOpenChange={onOpenChange} />, {
      queryClient
    });
  }

  function planned(next: unknown) {
    api.POST.mockImplementation(() => Promise.resolve({ data: next, response: json(200, next) }));
  }

  function choose(container: HTMLElement, file: File) {
    const input = container.ownerDocument.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    fireEvent.change(input, { target: { files: [file] } });
  }

  it("refuses a file that is not a package, at the field", async () => {
    const { container } = renderImport();
    // A browser reports a zip-based file under a zip type, which the picker lets through.
    choose(container, new File(["x"], "brev.zip", { type: "application/zip" }));
    expect(
      await screen.findByText("Filen är inget flödespaket. Välj en fil som slutar på .eneopkg.")
    ).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("shows what the package needs, guides until it is chosen and imports the draft", async () => {
    api.POST.mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith("/import-plan/")
          ? { data: plan, response: json(200, plan) }
          : {
              data: { flow_id: "flow-9", flow_name: "Brev" },
              response: json(201, {})
            }
      )
    );
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    // Nothing is wrong yet: the choice lies ahead, and the reason stays by the button alone.
    expect(await screen.findByText(progress(0))).toBeTruthy();
    expect(container.ownerDocument.querySelector(".astryx-banner")).toBeNull();
    // What the package is reads on the file's line, not as rows above the choices.
    expect(screen.getByText(/ · Version 1\.0\.0 · 2 steg$/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Brev" })).toBeTruthy();
    expect(screen.getByText("Besvarar brev.")).toBeTruthy();
    expect(screen.getByText("Används av: Skriv svar")).toBeTruthy();
    // The row says what the model does here; the package's name for it is what the exporter used.
    expect(screen.getByRole("heading", { name: "Språkmodell" })).toBeTruthy();
    expect(screen.getByText("Paketet byggdes med Skrivmodell")).toBeTruthy();
    const importButton = screen.getByRole("button", { name: "Importera som utkast" });
    expect(
      importButton.hasAttribute("disabled") || importButton.getAttribute("aria-disabled")
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("combobox", { name: /Lokal resurs för Skrivmodell/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Modell A" }));
    expect(await screen.findByText(progress(1))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Importera som utkast" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/spaces/space-1/flows/flow-9"));
    const importCall = api.POST.mock.calls.find(([path]) => String(path).endsWith("/imports/"));
    expect(importCall?.[1].body).toMatchObject({
      expected_content_checksum: "abc",
      selected_bindings: [
        {
          slot_ref: { kind: "model", slot: "writer", label: "Skrivmodell" },
          local_kind: "completion_model",
          local_id: "m-1"
        }
      ]
    });
  }, 20_000);

  it("says why a model of the space cannot stand in for the package's", async () => {
    const [model] = plan.dependency_resolutions;
    const withRejected = {
      ...plan,
      dependency_resolutions: [
        {
          ...model,
          rejected_candidates: [
            {
              candidate: { local_kind: "completion_model", local_id: "m-2", label: "Gemma 4" },
              reasons: ["model_capacity_unknown"]
            },
            {
              candidate: { local_kind: "transcription_model", local_id: "t-1", label: "Whisper" },
              reasons: ["model_kind_mismatch"]
            }
          ]
        }
      ]
    };
    api.POST.mockImplementation(() =>
      Promise.resolve({ data: withRejected, response: json(200, withRejected) })
    );
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(
      await screen.findByText(
        /^Gemma 4 kan inte väljas: Det är inte angivet hur mycket text modellen kan ta emot\./
      )
    ).toBeTruthy();
    // A model of the other kind is no candidate at all, so it is not listed.
    expect(screen.queryByText(/Whisper/)).toBeNull();
    fireEvent.click(screen.getByRole("combobox", { name: /Lokal resurs för Skrivmodell/ }));
    expect(await screen.findByRole("option", { name: "Modell A" })).toBeTruthy();
    await expectNoAxeViolations(container);
  }, 20_000);

  it("shows the chosen package as a file and lets the person swap it", async () => {
    api.POST.mockImplementation(() => Promise.resolve({ data: plan, response: json(200, plan) }));
    const { container } = renderImport();
    expect(screen.getByText("Dra hit ett flödespaket eller välj en fil.")).toBeTruthy();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText("brev.eneopkg")).toBeTruthy();
    expect(screen.queryByText("Dra hit ett flödespaket eller välj en fil.")).toBeNull();
    expect(screen.getByRole("button", { name: "Byt fil" })).toBeTruthy();
    await screen.findByText(progress(0));

    // A file that is no package keeps the one already chosen.
    choose(container, new File(["x"], "brev.zip", { type: "application/zip" }));
    expect(
      await screen.findByText("Filen är inget flödespaket. Välj en fil som slutar på .eneopkg.")
    ).toBeTruthy();
    expect(screen.getByText("brev.eneopkg")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledTimes(1);

    choose(container, new File(["zip"], "svar.eneopkg", { type: "application/zip" }));
    expect(await screen.findByText("svar.eneopkg")).toBeTruthy();
    expect(
      screen.queryByText("Filen är inget flödespaket. Välj en fil som slutar på .eneopkg.")
    ).toBeNull();
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    await expectNoAxeViolations(container);
  }, 20_000);

  it("keeps the error for what no choice here can lift", async () => {
    const [model] = plan.dependency_resolutions;
    const noCandidates = {
      ...plan,
      dependency_resolutions: [{ ...model, suggestions: [], eligible_candidate_count: 0 }]
    };
    api.POST.mockImplementation(() =>
      Promise.resolve({ data: noCandidates, response: json(200, noCandidates) })
    );
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText(BLOCKED)).toBeTruthy();
    expect(screen.getByText("Välj en lokal resurs för Skrivmodell.")).toBeTruthy();
    // Counting choices would promise what none can give: the footer points at the problem.
    expect(screen.getByText("Paketet kan inte importeras än: se problemen ovan.")).toBeTruthy();
    expect(screen.queryByText(progress(0))).toBeNull();
  });

  it("treats a Word template still to be given as a step ahead, not a problem", async () => {
    const [model] = plan.dependency_resolutions;
    const needsTemplate = {
      ...plan,
      dependency_resolutions: [
        {
          ...model,
          kind: "template_asset",
          slot_ref: { kind: "template_asset", slot: "brev", label: "Brevmall" },
          suggestions: [],
          template: { filename: "brev.docx", fields: [{ name: "namn" }], asset_path: null }
        }
      ]
    };
    api.POST.mockImplementation(() =>
      Promise.resolve({ data: needsTemplate, response: json(200, needsTemplate) })
    );
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText(progress(0))).toBeTruthy();
    expect(screen.queryByText(BLOCKED)).toBeNull();
  });

  it("goes to the Word template field and its message when the template is refused", async () => {
    const [model] = plan.dependency_resolutions;
    const needsTemplate = {
      ...plan,
      dependency_resolutions: [
        {
          ...model,
          kind: "template_asset",
          slot_ref: { kind: "template_asset", slot: "brev", label: "Brevmall" },
          suggestions: [],
          template: { filename: "brev.docx", fields: [{ name: "namn" }], asset_path: null }
        }
      ]
    };
    api.POST.mockResolvedValueOnce({ data: needsTemplate, response: json(200, needsTemplate) });
    api.POST.mockResolvedValueOnce({
      error: {
        message: "Mismatch",
        code: "flow_package_template_fields_mismatch",
        context: { missing_fields: ["namn"] }
      },
      response: json(400, {})
    });
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView");
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));
    await screen.findByText(progress(0));

    const templateInput = container.ownerDocument.querySelector<HTMLInputElement>(
      'input[type="file"][accept^=".docx"]'
    );
    fireEvent.change(templateInput!, {
      target: { files: [new File(["docx"], "egen.docx")] }
    });

    const message = await screen.findByText(/Filen används inte\. Mallens fält matchar inte/);
    const field = screen.getByRole("button", { name: /Word-fil till Brevmall/ });
    await waitFor(() => expect(document.activeElement).toBe(field));
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(scrolled.mock.contexts.some((element) => (element as Element).contains(message))).toBe(
      true
    );
    scrolled.mockRestore();
  });

  it("asks for a review before publishing beside the buttons, without a banner", async () => {
    const [model] = plan.dependency_resolutions;
    planned({ ...plan, can_publish_after_import: false, dependency_resolutions: [model] });
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    fireEvent.click(await screen.findByRole("combobox", { name: /Lokal resurs för Skrivmodell/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Modell A" }));

    expect(
      await screen.findByText(`${progress(1)} Granska resursvalen innan du publicerar.`)
    ).toBeTruthy();
    // The draft is said once, by the dialog's subtitle.
    expect(screen.queryByText(/Flödet importeras som utkast/)).toBeNull();
    expect(container.ownerDocument.querySelector(".astryx-banner")).toBeNull();
  });

  it("says which steps use a resource by number, not by the package's keys", async () => {
    const [model] = plan.dependency_resolutions;
    const keyed = {
      ...plan,
      dependency_resolutions: [
        { ...model, used_by_steps: ["step_8", "step_3", "step_4", "step_5", "step_10"] }
      ]
    };
    api.POST.mockImplementation(() => Promise.resolve({ data: keyed, response: json(200, keyed) }));
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText("Används av: Steg 3–5, 8, 10")).toBeTruthy();
  });

  it("does not offer its placeholder as a choice, and a choice can be cleared", async () => {
    api.POST.mockImplementation(() => Promise.resolve({ data: plan, response: json(200, plan) }));
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    const selector = await screen.findByRole("combobox", { name: /Lokal resurs för Skrivmodell/ });
    expect(selector.textContent).toContain("Välj lokal resurs");
    fireEvent.click(selector);
    fireEvent.click(await screen.findByRole("option", { name: "Modell A" }));
    await screen.findByText(progress(1));
    expect(screen.queryByRole("option", { name: "Välj lokal resurs" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^Rensa/ }));
    expect(await screen.findByText(progress(0))).toBeTruthy();
  });

  it("takes the whole screen on a phone, where a dialog's header would leave too little", () => {
    setViewport("phone");
    renderImport();
    expect(screen.getByRole("dialog").getAttribute("data-variant")).toBe("fullscreen");
  });

  it("says nothing more than the footer for a package that needs nothing", async () => {
    planned({ ...plan, dependency_resolutions: [] });
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText("Klart att importera.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Lokala resurser" })).toBeNull();
    expect(container.ownerDocument.querySelector(".astryx-banner")).toBeNull();
  });

  it("says that audio and speaker settings stay behind when the flow takes audio", async () => {
    planned({
      ...plan,
      dependency_resolutions: [],
      target_state: { audio_transcription_required: true, default_transcription_model_id: "t-1" }
    });
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText("Ljud- och talarinställningar följer inte med")).toBeTruthy();
    expect(screen.getByText(/Det nya flödet får ytans standardinställningar\./)).toBeTruthy();
    expect(screen.getByText("Klart att importera.")).toBeTruthy();
  });

  it("asks before closing over choices the person made, and closes at once without them", async () => {
    planned(plan);
    const onOpenChange = vi.fn();
    const { container } = renderImport(onOpenChange);
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));
    await screen.findByText(progress(0));

    fireEvent.click(screen.getByRole("combobox", { name: /Lokal resurs för Skrivmodell/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Modell A" }));
    await screen.findByText(progress(1));
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Stäng utan att importera?" });
    expect(onOpenChange).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: "Stäng" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  }, 20_000);

  it("closes without asking when no choice was made", async () => {
    planned(plan);
    const onOpenChange = vi.fn();
    const { container } = renderImport(onOpenChange);
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));
    await screen.findByText(progress(0));

    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("calls a broken file broken, under a title that says it was only read", async () => {
    api.POST.mockResolvedValue({
      error: { message: "Unsafe", code: "flow_package_zip_unsafe", context: { reason: "bad_zip" } },
      response: json(400, {})
    });
    const { container } = renderImport();
    choose(container, new File(["x"], "trasig.eneopkg", { type: "application/zip" }));

    expect(await screen.findByText("Paketet kunde inte läsas")).toBeTruthy();
    expect(
      screen.getByText(
        "Filen är trasig eller är inte ett flödespaket. Be avsändaren exportera paketet på nytt."
      )
    ).toBeTruthy();
    expect(screen.queryByText(/importerades inte|säkerhetskontrollerna/)).toBeNull();
  });

  it("says why the core refused the package", async () => {
    api.POST.mockResolvedValue({
      error: { message: "Bad", code: "flow_package_checksum_mismatch" },
      response: json(400, {})
    });
    const { container } = renderImport();
    choose(container, new File(["zip"], "brev.eneopkg", { type: "application/zip" }));
    expect(
      await screen.findByText(/Paketfilen är skadad eller har ändrats efter exporten/)
    ).toBeTruthy();
  });
});
