// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
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
        flow={makeFlow({ steps: [makeStep(1), makeStep(2, { output_mode: "http_post" })] })}
        open
        onOpenChange={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));
    expect(await screen.findByText(/Det gäller utdatainställningarna i steg 2\./)).toBeTruthy();
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
        model_kind: "completion",
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

  function renderImport() {
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
    return renderInApp(<FlowPackageImportDialog open onOpenChange={vi.fn()} />, { queryClient });
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
    expect(await screen.findByText("Endast .eneopkg-filer kan importeras.")).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("shows what the package needs, blocks until it is chosen and imports the draft", async () => {
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

    expect(await screen.findByText("Välj en lokal resurs för Skrivmodell.")).toBeTruthy();
    expect(screen.getByText("Används av: Skriv svar")).toBeTruthy();
    const importButton = screen.getByRole("button", { name: "Importera som utkast" });
    expect(
      importButton.hasAttribute("disabled") || importButton.getAttribute("aria-disabled")
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("combobox", { name: /Lokal resurs för Skrivmodell/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Modell A" }));
    await waitFor(() =>
      expect(screen.queryByText("Välj en lokal resurs för Skrivmodell.")).toBeNull()
    );
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
