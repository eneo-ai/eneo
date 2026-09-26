// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { MigrateModelDialog } from "./migrate-model-dialog";
import { type AdminModel, MODELS_KEY } from "./models";

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
    is_org_enabled: true,
    is_deprecated: false,
    deprecation_date: null,
    migrated_to_model_id: null
  }) as unknown as AdminModel;

const source = model("m-old", "gpt-4o");

function show() {
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/migration-validate")
      ? ok({
          compatible: false,
          requires_confirmation: true,
          warnings: ["Lower classification"],
          warning_codes: ["security_classification_insufficient"]
        })
      : ok({ assistants_count: 3, apps_count: 0, services_count: 0, spaces_count: 1 })
  );
  api.POST.mockImplementation(() => ok({ migrated_count: 3 }));
  const queryClient = testQueryClient();
  queryClient.setQueryData(MODELS_KEY, {
    completion_models: [source, model("m-new", "gpt-5")],
    embedding_models: [],
    transcription_models: [],
    image_models: []
  });
  renderInApp(
    <MigrateModelDialog model={source} kind="completion" open onOpenChange={() => {}} />,
    { queryClient }
  );
  return screen.getByRole("dialog", { name: "Migrera modell" });
}

const problemOf = (control: HTMLElement) =>
  document.getElementById(control.getAttribute("aria-describedby") ?? "")?.textContent;

it("shows a missing target, then an unconfirmed override, at its field on Migrate", async () => {
  const dialog = show();
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
  fireEvent.click(await screen.findByRole("option", { name: "gpt-5" }));
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
