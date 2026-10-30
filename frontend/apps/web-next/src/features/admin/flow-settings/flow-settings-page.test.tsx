// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import type { FlowSettings } from "./flow-settings";
import { flowSettingsFixture } from "./flow-settings-fixtures";
import { FlowSettingsPage } from "./flow-settings-page";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const PATHS: Record<string, keyof FlowSettings> = {
  "/api/v1/settings/flow-input-limits": "inputLimits",
  "/api/v1/settings/flow-runtime-policy": "runtime",
  "/api/v1/settings/flow-mapped-execution-policy": "mapped",
  "/api/v1/settings/flow-rag-evidence-policy": "ragEvidence",
  "/api/v1/settings/flow-document-render-limits": "documentRender",
  "/api/v1/settings/flow-evidence-policy": "evidence",
  "/api/v1/settings/flow-authoring-chat-policy": "authoringChat"
};

const MODELS_PATH = "/api/v1/ai-models/";
const catalogModel = (id: string, nickname: string, tools: boolean) => ({
  id,
  name: id,
  nickname,
  org: "OpenAI",
  max_input_tokens: 128_000,
  max_output_tokens: 4096,
  is_deprecated: false,
  is_org_enabled: true,
  can_access: true,
  vision: false,
  reasoning: false,
  supports_tool_calling: tools
});
const CATALOG = {
  completion_models: [
    catalogModel("gpt-strong", "Stark modell", true),
    catalogModel("gpt-plain", "Utan verktyg", false)
  ],
  embedding_models: [],
  transcription_models: [],
  image_models: []
};

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const refused = (status: number, error: unknown) =>
  Promise.resolve({ error, response: new Response("{}", { status }) });

let current: FlowSettings;

function serve(settings: FlowSettings) {
  current = settings;
  api.GET.mockImplementation((path: string) =>
    ok(path === MODELS_PATH ? CATALOG : current[PATHS[path]!])
  );
  // Answers a PATCH with the section and the body applied, as the backend resolves it.
  api.PATCH.mockImplementation((path: string, { body }: { body: Record<string, unknown> }) => {
    const section = PATHS[path]!;
    current = { ...current, [section]: { ...current[section], ...body } };
    return ok(current[section]);
  });
}

beforeEach(() => serve(flowSettingsFixture()));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

/** Types into a NumberInput and leaves it, which commits the value. */
function enter(label: string, value: string) {
  const input = screen.getByLabelText(label);
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
  return input;
}

async function show(appContext?: Parameters<typeof renderInApp>[1]) {
  const view = renderInApp(<FlowSettingsPage />, appContext);
  await screen.findByLabelText("Antal filer per körning");
  return view;
}

// The page renders about thirty Astryx fields; rendering and axe over all of
// them take several seconds on a busy runner.
describe("flow settings page", { timeout: 20_000 }, () => {
  it("shows every non-retention setting group without axe violations", async () => {
    const { container } = await show();

    expect(screen.getByRole("heading", { level: 1, name: "Flöden" })).toBeTruthy();
    for (const name of [
      "Filer som bifogas",
      "Ljudfiler som transkriberas",
      "Samtidiga körningar",
      "Tidsgränser per steg",
      "Steg som körs en gång per fil",
      "Sparad källtext",
      "Genererade dokument",
      "Bevisunderlag från känsliga ytor",
      "Flödesassistenten"
    ]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeTruthy();
    }
    expect(screen.queryByText(/gallring/i)).toBeNull();
    expect(screen.getByRole("switch", { name: /Tillåt nya steg som körs per fil/ })).toBeTruthy();
    // The audit log filtered to what a save here writes.
    expect(
      screen
        .getByRole("link", { name: "Ändringar loggas i granskningsloggen" })
        .getAttribute("href")
    ).toBe("/admin/audit-logs?actions=tenant_settings_updated");
    expect(screen.getByText("Inga osparade ändringar")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("saves only the changed fields, endpoint by endpoint, and says so", async () => {
    await show();
    enter("Antal filer per körning", "40");
    enter("Största textavsnitt", "8");
    fireEvent.click(screen.getByRole("switch", { name: /Den som startade körningen/ }));
    expect(screen.getByText("3 osparade ändringar")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));

    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(3));
    expect(api.PATCH.mock.calls).toEqual([
      ["/api/v1/settings/flow-input-limits", { body: { max_files_per_run: 40 } }],
      ["/api/v1/settings/flow-rag-evidence-policy", { body: { max_recorded_passage_bytes: 8192 } }],
      [
        "/api/v1/settings/flow-evidence-policy",
        { body: { allow_run_owner_raw_export_class3: true } }
      ]
    ]);
    // Said in the save bar and announced politely.
    expect(await screen.findAllByText("Flödesinställningarna är sparade.")).not.toHaveLength(0);
  });

  it("saves the flow chat's default model from the models that can use tools", async () => {
    await show();
    const picker = await screen.findByRole("button", {
      name: "Modell för flödesassistenten: Ytans standardmodell"
    });
    fireEvent.click(picker);
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      expect.stringContaining("Ytans standardmodell"),
      expect.stringContaining("Stark modell")
    ]);
    fireEvent.click(screen.getByRole("option", { name: /Stark modell/ }));
    expect(screen.getByText("1 osparad ändring")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/flow-authoring-chat-policy", {
        body: { completion_model_id: "gpt-strong" }
      })
    );
    expect(await screen.findAllByText("Flödesinställningarna är sparade.")).not.toHaveLength(0);
  });

  it("shows a refused default model at its field and moves focus there", async () => {
    await show();
    fireEvent.click(await screen.findByRole("button", { name: /^Modell för flödesassistenten: / }));
    // The open list moves focus to its search a frame later; choose after that,
    // as a person does, so only the refusal decides where focus goes next.
    const search = await screen.findByRole("combobox", { name: "Sökalternativ" });
    await waitFor(() => expect(document.activeElement).toBe(search));
    fireEvent.click(await screen.findByRole("option", { name: /Stark modell/ }));
    api.PATCH.mockImplementation(() =>
      refused(400, {
        message: "The flow chat needs a model that supports tools.",
        code: "flow_authoring_model_without_tools"
      })
    );

    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));

    const picker = await screen.findByRole("button", {
      name: "Modell för flödesassistenten: Stark modell"
    });
    await waitFor(() => expect(document.activeElement).toBe(picker));
    expect(screen.getAllByText(/Modellen kan inte använda verktyg/).length).toBeGreaterThan(0);
    await expectNoAxeViolations(document.body);
  });

  it("asks before a link in the app leaves unsaved changes behind", async () => {
    await show();
    const audit = screen.getByRole("link", { name: "Ändringar loggas i granskningsloggen" });
    fireEvent.click(audit);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(router.push).toHaveBeenCalledTimes(0);

    enter("Antal filer per körning", "40");
    fireEvent.click(audit);
    const dialog = await screen.findByRole("alertdialog", { name: "Lämna sidan?" });
    await expectNoAxeViolations(document.body);
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByText("1 osparad ändring")).toBeTruthy();

    fireEvent.click(audit);
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Lämna sidan" })
    );
    expect(router.push).toHaveBeenCalledWith("/admin/audit-logs?actions=tenant_settings_updated");
  });

  it("moves focus to a problem at its field on save and sends nothing", async () => {
    const { container } = await show();
    fireEvent.click(screen.getByRole("button", { name: /Tidsgränser/ }));
    const normal = enter("Normal tidsgräns per steg", "1500");

    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));

    expect(document.activeElement).toBe(normal);
    expect(normal.getAttribute("aria-invalid")).toBe("true");
    const describedBy = normal.getAttribute("aria-describedby") ?? "";
    expect(
      describedBy
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent ?? "")
        .join(" ")
    ).toContain("Den normala tidsgränsen får inte vara längre än den längsta körtiden.");
    expect(api.PATCH).not.toHaveBeenCalled();
    // The open time limits, with a problem shown, pass axe too.
    await expectNoAxeViolations(container);
  });

  it("shows a refusal at the field it names and keeps what was saved before it", async () => {
    await show();
    enter("Antal filer per körning", "40");
    enter("Högsta antal samtidiga körningar", "6");
    api.PATCH.mockImplementation((path: string) =>
      path.endsWith("flow-runtime-policy")
        ? refused(400, {
            message: "max_concurrent_runs exceeds the server capacity.",
            code: "max_concurrent_runs_exceeds_server_capacity"
          })
        : ok({ ...current.inputLimits, max_files_per_run: 40 })
    );

    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));

    const runs = screen.getByLabelText("Högsta antal samtidiga körningar");
    await waitFor(() => expect(document.activeElement).toBe(runs));
    expect(runs.getAttribute("aria-invalid")).toBe("true");
    const alert = screen
      .getAllByRole("alert")
      .find((element) => element.textContent?.includes("Ändringarna sparades inte"));
    expect(alert?.textContent).toContain("En del sparades.");
    // The saved file count is no longer unsaved; the refused run limit is.
    expect(screen.getByText("1 osparad ändring")).toBeTruthy();
  });

  it("switches new per-file steps off with the explicit opt-out", async () => {
    await show();
    fireEvent.click(screen.getByRole("switch", { name: /Tillåt nya steg som körs per fil/ }));
    expect(
      screen.getByText(
        "Nya steg som körs per fil är blockerade. Redan publicerade flöden fungerar som vanligt."
      )
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/flow-mapped-execution-policy", {
        body: { max_provider_calls_per_mapped_step: null }
      })
    );
  });

  it("lets the run limit follow the server capacity again and keeps focus on the field", async () => {
    const runtime = {
      ...flowSettingsFixture().runtime,
      max_concurrent_runs: 8,
      max_concurrent_runs_override: 12,
      max_concurrent_runs_capacity: 8
    };
    serve(flowSettingsFixture({ runtime }));
    api.PATCH.mockImplementation(() => ok({ ...runtime, max_concurrent_runs_override: null }));
    await show();
    expect(screen.getByText(/Begränsas till 8 eftersom servern inte klarar fler/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Använd serverns kapacitet" }));

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/flow-runtime-policy", {
        body: { max_concurrent_runs: null }
      })
    );
    // The answer has no saved value: the button goes, focus lands on the limit.
    const runs = screen.getByLabelText("Högsta antal samtidiga körningar");
    await waitFor(() => expect(document.activeElement).toBe(runs));
    expect(screen.queryByRole("button", { name: "Använd serverns kapacitet" })).toBeNull();
  });

  it("restores the mapped call ceiling to the deployment default", async () => {
    serve(
      flowSettingsFixture({
        mapped: {
          ...flowSettingsFixture().mapped,
          max_provider_calls_per_mapped_step: 40,
          max_provider_calls_source: "organization"
        }
      })
    );
    api.PATCH.mockImplementation(() =>
      ok({
        ...current.mapped,
        max_provider_calls_per_mapped_step: 100,
        max_provider_calls_source: "deployment_default"
      })
    );
    await show();

    fireEvent.click(
      screen.getByRole("button", { name: "Återställ till driftmiljöns standard (100 anrop)" })
    );

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/flow-mapped-execution-policy", {
        body: { restore_max_provider_calls_default: true }
      })
    );
    const calls = screen.getByLabelText("Modellanrop per steg") as HTMLInputElement;
    await waitFor(() => expect(document.activeElement).toBe(calls));
    expect(calls.value).toBe("100");
    expect(screen.getByText("Följer driftmiljöns standard.")).toBeTruthy();
  });

  it("disables the run limit with the reason when the server has no capacity", async () => {
    serve(
      flowSettingsFixture({
        runtime: {
          ...flowSettingsFixture().runtime,
          max_concurrent_runs: 0,
          max_concurrent_runs_capacity: 0
        }
      })
    );
    await show();
    const group = screen
      .getByRole("heading", { level: 2, name: "Samtidiga körningar" })
      .closest<HTMLElement>("#flow-runs")!;
    const runs = within(group).getByLabelText("Högsta antal samtidiga körningar");
    expect(runs.getAttribute("aria-disabled") ?? runs.getAttribute("disabled")).not.toBeNull();
    expect(within(group).getAllByText(/serverns kapacitet är 0/).length).toBeGreaterThan(0);
  });
});
