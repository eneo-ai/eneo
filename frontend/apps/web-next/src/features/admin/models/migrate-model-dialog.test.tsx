// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { MigrateModelDialog } from "./migrate-model-dialog";
import { type AdminModel, type MigratableModelKind, MODELS_KEY } from "./models";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const model = (id: string, name: string) =>
  ({
    id,
    name,
    nickname: null,
    provider_id: "provider",
    is_org_enabled: true,
    is_deprecated: false,
    deprecation_date: null,
    migrated_to_model_id: null
  }) as unknown as AdminModel;

const source = model("m-old", "gpt-4o");

const impactedEntities = (
  [
    ["assistant", "Upphandling"],
    ["app", "Protokoll"],
    ["service", "Ärendesortering"],
    ["assistant_template", "Avtalsgranskning"],
    ["app_template", "Mötesmall"]
  ] as const
).map(([entity_type, entity_name], index) => ({
  entity_id: String(index),
  entity_type,
  entity_name,
  space_name: "Kommunen",
  owner_name: "Anna"
}));

function show({
  codes = ["security_classification_insufficient"],
  warnings = ["Lower classification"],
  items = impactedEntities,
  spaces = 1,
  kind = "completion",
  sourceModel = source,
  readFailure
}: {
  codes?: string[];
  warnings?: string[];
  items?: typeof impactedEntities;
  spaces?: number;
  kind?: MigratableModelKind;
  sourceModel?: AdminModel;
  readFailure?: string;
} = {}) {
  api.GET.mockImplementation((path: string) => {
    if (readFailure && path.endsWith(readFailure)) return Promise.reject(new Error("Unavailable"));
    if (path.endsWith("/migration-validate"))
      return ok({
        compatible: codes.length === 0,
        requires_confirmation: codes.length > 0,
        warnings,
        warning_codes: codes
      });
    if (path.endsWith("/usage/details")) return ok({ items, total: items.length });
    return ok({
      assistants_count: items.length,
      apps_count: 0,
      services_count: 0,
      spaces_count: spaces,
      total_count: items.length + spaces
    });
  });
  api.POST.mockImplementation(() => ok({ success: true, migrated_count: items.length }));
  const queryClient = testQueryClient();
  const models = [
    source,
    model("m-new", "gpt-5"),
    model("m-other", "replacement-two"),
    { ...model("global", "Global model"), provider_id: null }
  ];
  queryClient.setQueryData(MODELS_KEY, {
    completion_models: models,
    embedding_models: [],
    transcription_models: models,
    image_models: []
  });
  const onOpenChange = vi.fn();
  const props = { model: sourceModel, kind, open: true, onOpenChange };
  const rendered = renderInApp(<MigrateModelDialog {...props} />, { queryClient });
  return {
    dialog: screen.getByRole("dialog", { name: "Migrera modell" }),
    ...rendered,
    onOpenChange,
    props
  };
}

async function choose(dialog: HTMLElement, name = "GPT-5") {
  fireEvent.keyDown(within(dialog).getByRole("combobox", { name: "Migreringsmål" }), {
    key: "Enter"
  });
  fireEvent.click(await screen.findByRole("option", { name }));
  await waitFor(() =>
    expect(within(dialog).getByRole("button", { name: "Migrera" }).hasAttribute("disabled")).toBe(
      false
    )
  );
}

const problemOf = (control: HTMLElement) =>
  document.getElementById(control.getAttribute("aria-describedby") ?? "")?.textContent;

it("shows a missing target, then an unconfirmed override, at its field on Migrate", async () => {
  const { dialog } = show();
  const migrate = within(dialog).getByRole("button", { name: "Migrera" });
  // Waits for the impact, then is never disabled for what the admin must choose.
  await waitFor(() => expect(migrate.hasAttribute("disabled")).toBe(false));
  migrate.focus();

  fireEvent.click(migrate);
  const target = within(dialog).getByRole("combobox", { name: "Migreringsmål" });
  expect(document.activeElement).toBe(target);
  expect(target.getAttribute("aria-invalid")).toBe("true");
  expect(problemOf(target)).toBe("Välj en modell att migrera till.");

  fireEvent.keyDown(target, { key: "Enter" });
  fireEvent.click(await screen.findByRole("option", { name: "GPT-5" }));
  const override = await within(dialog).findByRole("checkbox", {
    name: /vill tvinga igenom den/
  });
  await waitFor(() => expect(migrate.hasAttribute("disabled")).toBe(false));
  migrate.focus();
  fireEvent.click(migrate);
  expect(document.activeElement).toBe(override);
  expect(override.getAttribute("aria-invalid")).toBe("true");
  expect(problemOf(override)).toBe("Kryssa i rutan för att tvinga igenom migreringen.");
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.click(override);
  fireEvent.click(migrate);
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/completion-models/{model_id}/migrate", {
      params: { path: { model_id: "m-old" } },
      body: { to_model_id: "m-new", confirm_migration: true, force_override: true }
    })
  );
});

it("names the affected resources, space and owner and excludes global targets", async () => {
  const { dialog } = show();
  for (const { entity_name } of impactedEntities)
    expect(await within(dialog).findByText(entity_name)).toBeTruthy();
  expect(within(dialog).getAllByText("Kommunen")).toHaveLength(5);
  expect(within(dialog).getAllByText("Anna")).toHaveLength(5);
  fireEvent.keyDown(within(dialog).getByRole("combobox", { name: "Migreringsmål" }), {
    key: "Enter"
  });
  expect(screen.queryByRole("option", { name: "Global model" })).toBeNull();
});

it("requires compatibility acknowledgement with resources and separates information notes", async () => {
  const { dialog } = show({
    codes: ["lacks_vision", "kwargs_reset", "future_warning"],
    warnings: ["Vision", "Settings", "An unknown warning"]
  });
  await choose(dialog);
  expect(within(dialog).getByText("Kompatibilitetsvarningar")).toBeTruthy();
  expect(within(dialog).getByText("Bra att veta")).toBeTruthy();
  expect(within(dialog).getByText("An unknown warning")).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  expect(api.POST).not.toHaveBeenCalled();
  const acknowledgement = within(dialog).getByRole("checkbox", {
    name: "Fortsätt även om kompatibilitetsvarningar finns"
  });
  expect(document.activeElement).toBe(acknowledgement);
  fireEvent.click(acknowledgement);
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/completion-models/{model_id}/migrate", {
      params: { path: { model_id: "m-old" } },
      body: { to_model_id: "m-new", confirm_migration: true, force_override: false }
    })
  );
});

it.each(["completion", "transcription"] as const)(
  "requires security acknowledgement for %s even with spaces only",
  async (kind) => {
    const { dialog } = show({ kind, items: [] });
    await choose(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /vill tvinga igenom den/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith(`/api/v1/${kind}-models/{model_id}/migrate`, {
        params: { path: { model_id: "m-old" } },
        body: { to_model_id: "m-new", confirm_migration: true, force_override: true }
      })
    );
  }
);

it("does not require compatibility acknowledgement for spaces only", async () => {
  const { dialog } = show({
    codes: ["lacks_vision", "kwargs_reset"],
    warnings: ["Vision", "Settings"],
    items: [],
    spaces: 8
  });
  await choose(dialog);
  expect(within(dialog).queryByRole("checkbox")).toBeNull();
  expect(within(dialog).queryByText("Kompatibilitetsvarningar")).toBeNull();
  expect(within(dialog).queryByText("Bra att veta")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/completion-models/{model_id}/migrate", {
      params: { path: { model_id: "m-old" } },
      body: { to_model_id: "m-new", confirm_migration: true, force_override: false }
    })
  );
});

it("does not require acknowledgement for information alone", async () => {
  const { dialog } = show({ codes: ["kwargs_reset"], warnings: ["Settings"] });
  await choose(dialog);
  expect(within(dialog).getByText("Bra att veta")).toBeTruthy();
  expect(within(dialog).queryByRole("checkbox")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalled());
});

it("resets acknowledgement on target, source and fresh opening and blocks pending validation", async () => {
  const { dialog, rerender, props } = show();
  await choose(dialog);
  fireEvent.click(within(dialog).getByRole("checkbox"));
  const get = api.GET.getMockImplementation();
  api.GET.mockImplementation((path: string, options: unknown) =>
    path.endsWith("/migration-validate") ? new Promise(() => {}) : get?.(path, options)
  );
  fireEvent.keyDown(within(dialog).getByRole("combobox", { name: "Migreringsmål" }), {
    key: "Enter"
  });
  fireEvent.click(await screen.findByRole("option", { name: "Replacement Two" }));
  expect(within(dialog).getByRole("button", { name: "Migrera" }).hasAttribute("disabled")).toBe(
    true
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  expect(api.POST).not.toHaveBeenCalled();
  await choose(dialog);
  expect(within(dialog).getByRole("checkbox").getAttribute("data-state")).toBe("unchecked");
  fireEvent.click(within(dialog).getByRole("checkbox"));
  rerender(<MigrateModelDialog {...props} open={false} />);
  rerender(<MigrateModelDialog {...props} />);
  expect(screen.getByRole("combobox", { name: "Migreringsmål" }).textContent).toContain(
    "Välj målmodell"
  );
  rerender(<MigrateModelDialog {...props} model={model("source-two", "Second source")} />);
  expect(screen.queryByRole("checkbox")).toBeNull();
});

it.each(["details", "validation"])("blocks migration on a failed %s read", async (failure) => {
  const { dialog } = show({
    codes: [],
    warnings: [],
    readFailure: failure === "details" ? "/usage/details" : "/migration-validate"
  });
  fireEvent.keyDown(within(dialog).getByRole("combobox", { name: "Migreringsmål" }), {
    key: "Enter"
  });
  fireEvent.click(await screen.findByRole("option", { name: "GPT-5" }));
  expect(
    await within(dialog).findByText(
      failure === "details"
        ? "Kunde inte läsa migreringens påverkan. Migreringen blockeras tills påverkan kan kontrolleras."
        : "Kunde inte validera målmodellen. Välj en annan målmodell eller försök igen."
    )
  ).toBeTruthy();
  expect(within(dialog).getByRole("button", { name: "Migrera" }).hasAttribute("disabled")).toBe(
    true
  );
  expect(api.POST).not.toHaveBeenCalled();
});

it("keeps a failed migration open and never announces success", async () => {
  const { dialog, onOpenChange } = show({ codes: [], warnings: [] });
  api.POST.mockRejectedValue(new Error("Migration failed"));
  await choose(dialog);
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.success).not.toHaveBeenCalled();
  expect(onOpenChange).not.toHaveBeenCalled();
});

it("cannot migrate a source already marked as migrated", async () => {
  const { dialog } = show({
    sourceModel: { ...source, migrated_to_model_id: "m-new" } as AdminModel
  });
  expect(await within(dialog).findByText("Upphandling")).toBeTruthy();
  expect(within(dialog).getByRole("button", { name: "Migrera" }).hasAttribute("disabled")).toBe(
    true
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  expect(api.POST).not.toHaveBeenCalled();
});

it("does not announce success when a migration returns an unsuccessful result", async () => {
  const { dialog, onOpenChange } = show({ codes: [], warnings: [] });
  api.POST.mockImplementation(() => ok({ success: false, migrated_count: 0 }));
  await choose(dialog);
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(toast.success).not.toHaveBeenCalled();
  expect(onOpenChange).not.toHaveBeenCalled();
});
