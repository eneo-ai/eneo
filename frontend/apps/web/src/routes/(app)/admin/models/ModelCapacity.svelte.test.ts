import type { CompletionModel } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { writable } from "svelte/store";
import { beforeEach, expect, it, vi } from "vitest";

const { updateCompletion } = vi.hoisted(() => ({
  updateCompletion: vi.fn(async (_identifier: { id: string }, _payload: unknown) => ({}))
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ tenantModels: { updateCompletion } })
}));
vi.mock("$app/navigation", () => ({ invalidate: vi.fn() }));
vi.mock("$lib/features/security-classifications/SecurityContext", () => ({
  getSecurityContext: () => ({ security_classifications: [] })
}));

import EditModelDialog from "./EditModelDialog.svelte";
import ModelDetailDialog from "./ModelDetailDialog.svelte";
import { setLocale } from "$lib/paraglide/runtime";
import { m } from "$lib/paraglide/messages";

function model(ceilings: { input?: number | null; output?: number | null } = {}): CompletionModel {
  return {
    id: "m1",
    name: "custom",
    nickname: "Custom",
    hosting: "swe",
    max_input_tokens: ceilings.input === undefined ? 272000 : ceilings.input,
    max_output_tokens: ceilings.output === undefined ? 128000 : ceilings.output,
    vision: false,
    reasoning: false,
    is_deprecated: false,
    supported_model_kwargs: {},
    token_limit: 272000
  };
}

beforeEach(() => {
  updateCompletion.mockClear();
  setLocale("sv", { reload: false });
});

it("saves a changed input limit", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) });
  await expect.element(input).toBeVisible();
  await input.fill("500000");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion).toHaveBeenCalledWith(
    { id: "m1" },
    expect.objectContaining({ max_input_tokens: 500000 })
  );
});

it.each(["input", "output"] as const)(
  "refuses to save a blank %s limit, as develop does",
  async (dimension) => {
    render(EditModelDialog, {
      openController: writable(true),
      model: model(),
      type: "completionModel"
    });
    const label = dimension === "input" ? m.max_input_tokens() : m.max_output_tokens();
    await page.getByRole("spinbutton", { name: new RegExp(label) }).fill("");
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await expect.element(page.getByText(m.completion_token_budgets_required())).toBeVisible();
    expect(updateCompletion).not.toHaveBeenCalled();
  }
);

it("keeps both limits when the model is renamed", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) });
  const output = page.getByRole("spinbutton", { name: new RegExp(m.max_output_tokens()) });
  await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("renamed");
  await expect.element(input).toHaveValue(272000);
  await expect.element(output).toHaveValue(128000);
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  const patch = updateCompletion.mock.calls[0][1];
  expect(patch).toMatchObject({ name: "renamed" });
  // Untouched limits are omitted, and the server keeps them.
  expect(patch).not.toHaveProperty("max_input_tokens");
  expect(patch).not.toHaveProperty("max_output_tokens");
});

it("omits the input limit when nothing touched it and the route stayed", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  await page.getByRole("textbox", { name: new RegExp(m.display_name()) }).fill("Nytt namn");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).not.toHaveProperty("max_input_tokens");
});

it("sends a limit changed together with a rename", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) });
  await input.fill("500000");
  await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("route-b");
  await expect.element(input).toHaveValue(500000);
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).toMatchObject({
    name: "route-b",
    max_input_tokens: 500000
  });
});

it("asks for the limits before saving a model that has none stored", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model({ input: null, output: null }),
    type: "completionModel"
  });
  await page.getByRole("textbox", { name: new RegExp(m.display_name()) }).fill("Nytt visningsnamn");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.element(page.getByText(m.completion_token_budgets_required())).toBeVisible();
  expect(updateCompletion).not.toHaveBeenCalled();

  await page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) }).fill("100000");
  await page.getByRole("spinbutton", { name: new RegExp(m.max_output_tokens()) }).fill("8000");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).toMatchObject({
    display_name: "Nytt visningsnamn",
    max_input_tokens: 100000,
    max_output_tokens: 8000
  });
});

it("renders only the two deployment limits in the editor and detail", async () => {
  const editor = render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  await expect
    .element(page.getByRole("spinbutton", { name: "Kontextfönster (tokens)", exact: true }))
    .not.toBeInTheDocument();
  editor.unmount();
  render(ModelDetailDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  await expect
    .element(page.getByRole("cell", { name: "Kontextfönster (tokens)", exact: true }))
    .not.toBeInTheDocument();
});

it.each([
  [
    "en",
    "Maximum input tokens accepted by this deployment. If the provider specifies only a shared context window, enter that value. Eneo reserves room for the response within this limit.",
    "Maximum tokens this deployment allows for one generated response, including reasoning tokens where the provider counts them toward this limit. Eneo may request fewer tokens to fit the request."
  ],
  [
    "sv",
    "Maximalt antal indatatokens för modellen i den här driftsmiljön. Om leverantören bara anger ett gemensamt kontextfönster anger du det värdet. Eneo reserverar utrymme för svaret inom gränsen.",
    "Maximalt antal tokens i ett svar från modellen i den här driftsmiljön, inklusive resonemangstokens om leverantören räknar in dem. Eneo kan begära färre tokens för att hela anropet ska rymmas."
  ]
] as const)("explains both deployment limits in %s", (locale, inputHelp, outputHelp) => {
  setLocale(locale, { reload: false });
  expect(m.max_input_tokens_help()).toBe(inputHelp);
  expect(m.max_output_tokens_help()).toBe(outputHelp);
});
