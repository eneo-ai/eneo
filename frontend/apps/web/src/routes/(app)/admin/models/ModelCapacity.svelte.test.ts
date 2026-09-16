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

function model(
  window: number | null,
  ceilings: { input?: number | null; output?: number | null } = {}
): CompletionModel {
  return {
    id: "m1",
    name: "custom",
    nickname: "Custom",
    hosting: "swe",
    max_input_tokens: ceilings.input === undefined ? 272000 : ceilings.input,
    max_output_tokens: ceilings.output === undefined ? 128000 : ceilings.output,
    context_window_tokens: window,
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
] as const)("saves a changed window %s as %s", async (raw, expected) => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(400000),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: "Kontextfönster (tokens)", exact: true });
  await expect.element(input).toBeVisible();
  await input.fill(raw);
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion).toHaveBeenCalledWith(
    { id: "m1" },
    expect.objectContaining({ context_window_tokens: expected })
  );
});

it("withdraws the window when saving a renamed model, matching the emptied field", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(400000),
    type: "completionModel"
  });
  const input = page.getByRole("spinbutton", { name: "Kontextfönster (tokens)", exact: true });
  await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("renamed");
  // The declaration belonged to the old route, so the field empties and the
  // save says so rather than leaving the stored number to the server's rule.
  await expect.element(input).toHaveValue(null);
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).toHaveProperty("context_window_tokens", null);
});

it("omits the window when nothing touched it and the route stayed", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(400000),
    type: "completionModel"
  });
  await page.getByRole("textbox", { name: new RegExp(m.display_name()) }).fill("Nytt namn");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).not.toHaveProperty("context_window_tokens");
});

it("shows an unknown shared window in the Swedish detail dialog", async () => {
  render(ModelDetailDialog, {
    openController: writable(true),
    model: model(null),
    type: "completionModel"
  });
  await expect.element(page.getByRole("cell", { name: "okänt", exact: true })).toBeVisible();
});

it.each([false, true])(
  "clears a touched declaration on manual rename; redeclare=%s",
  async (redeclare) => {
    render(EditModelDialog, {
      openController: writable(true),
      model: model(400000),
      type: "completionModel"
    });
    const input = page.getByRole("spinbutton", { name: "Kontextfönster (tokens)", exact: true });
    await input.fill("500000");
    await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("route-b");
    await expect.element(input).toHaveValue(null);
    if (redeclare) await input.fill("600000");
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
    expect(updateCompletion.mock.calls[0][1]).toMatchObject({ name: "route-b" });
    expect(updateCompletion.mock.calls[0][1]).toHaveProperty(
      "context_window_tokens",
      redeclare ? 600000 : null
    );
  }
);

it("saves an ordinary edit of a model whose capacity is undeclared", async () => {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(null, { input: null, output: null }),
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
    model: model(400000),
    type: "completionModel"
  });
  await page.getByRole("textbox", { name: new RegExp(m.model_identifier()) }).fill("route-b");
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await expect.poll(() => updateCompletion.mock.calls.length).toBe(1);
  expect(updateCompletion.mock.calls[0][1]).toMatchObject({
    name: "route-b",
    max_input_tokens: null,
    max_output_tokens: null,
    context_window_tokens: null
  });
});
