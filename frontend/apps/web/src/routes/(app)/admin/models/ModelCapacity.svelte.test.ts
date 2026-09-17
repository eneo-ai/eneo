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

it.each([
  ["", null],
  ["500000", 500000]
] as const)("saves a changed input limit %s as %s", async (raw, expected) => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) });
  await expect.element(input).toBeVisible();
  await input.fill(raw);
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion).toHaveBeenCalledWith(
    { id: "m1" },
    expect.objectContaining({ max_input_tokens: expected })
  );
});

it("withdraws the input limit when saving a renamed model, matching the emptied field", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) });
  await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("renamed");
  // The declaration belonged to the old route, so the field empties and the
  // save says so rather than leaving the stored number to the server's rule.
  await expect.element(input).toHaveValue(null);
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).toHaveProperty("max_input_tokens", null);
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

it.each([false, true])(
  "clears a touched declaration on manual rename; redeclare=%s",
  async (redeclare) => {
    render(EditModelDialog, {
      openController: writable(true),
      model: model(),
      type: "completionModel"
    });
    const input = page.getByRole("spinbutton", { name: new RegExp(m.max_input_tokens()) });
    await input.fill("500000");
    await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("route-b");
    await expect.element(input).toHaveValue(null);
    if (redeclare) await input.fill("600000");
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
    expect(updateCompletion.mock.calls[0][1]).toMatchObject({ name: "route-b" });
    expect(updateCompletion.mock.calls[0][1]).toHaveProperty(
      "max_input_tokens",
      redeclare ? 600000 : null
    );
  }
);

it("saves an ordinary edit of a model whose capacity is undeclared", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model({ input: null, output: null }),
    type: "completionModel"
  });
  await page.getByRole("textbox", { name: new RegExp(m.display_name()) }).fill("Nytt visningsnamn");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  // Nothing about capacity is stated, so an undeclared model stays undeclared.
  const patch = updateCompletion.mock.calls[0][1];
  expect(patch).not.toHaveProperty("max_input_tokens");
  expect(patch).not.toHaveProperty("max_output_tokens");
  expect(patch).toMatchObject({ display_name: "Nytt visningsnamn" });
});

it("withdraws both ceilings when the model identifier changes", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("route-b");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).toMatchObject({
    name: "route-b",
    max_input_tokens: null,
    max_output_tokens: null
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

it("keeps both clears after changing back and retrying a failed save", async () => {
  updateCompletion.mockRejectedValueOnce(new Error("Save failed"));
  render(EditModelDialog, {
    openController: writable(true),
    model: model(),
    type: "completionModel"
  });
  const identifier = page.getByRole("textbox", { name: new RegExp(m.model_identifier()) });
  await identifier.fill("route-b");
  await identifier.fill("custom");
  const save = page.getByRole("button", { name: m.save(), exact: true });
  await save.click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  await expect.element(save).toBeEnabled();
  await save.click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(2);
  for (const [, payload] of updateCompletion.mock.calls) {
    expect(payload).toMatchObject({
      name: "custom",
      max_input_tokens: null,
      max_output_tokens: null
    });
    expect(payload).not.toHaveProperty("context_window_tokens");
  }
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
