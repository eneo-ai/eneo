import type { CompletionModel } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { expect, it, vi } from "vitest";

import ModelAvailabilityList from "./ModelAvailabilityList.svelte";

function model(id: string, nickname: string, meets: boolean) {
  return {
    id,
    name: id,
    nickname,
    org: "OpenAI",
    meets_security_classification: meets
  } as unknown as CompletionModel & { meets_security_classification: boolean };
}

it("lets an admin remove a linked model below the space's classification, never add one", async () => {
  const onToggle = vi.fn();
  render(ModelAvailabilityList, {
    models: [
      model("linked-below", "Linked below", false),
      model("unlinked-below", "Unlinked below", false),
      model("usable", "Usable", true)
    ],
    selectedIds: ["linked-below", "usable"],
    onToggle
  });

  const linkedBelow = page.getByRole("switch", { name: /Linked below/ });
  await expect.element(linkedBelow).toBeChecked();
  await expect.element(linkedBelow).toBeEnabled();
  await expect.element(page.getByRole("switch", { name: /Unlinked below/ })).toBeDisabled();
  await linkedBelow.click();
  expect(onToggle).toHaveBeenCalledTimes(1);
  expect(onToggle.mock.calls[0][0]).toMatchObject({ id: "linked-below" });

  // Forced past the disabled row, the switch still does not add the model.
  await page.getByRole("switch", { name: /Unlinked below/ }).click({ force: true });
  expect(onToggle).toHaveBeenCalledTimes(1);
});

it("lets an admin remove a linked model the tenant disabled, never add one", async () => {
  const onToggle = vi.fn();
  const disabled = (id: string, nickname: string) => ({
    ...model(id, nickname, true),
    is_org_enabled: false
  });
  render(ModelAvailabilityList, {
    models: [disabled("linked-disabled", "Linked disabled"), disabled("other", "Other disabled")],
    selectedIds: ["linked-disabled"],
    onToggle
  });

  const linked = page.getByRole("switch", { name: /Linked disabled/ });
  await expect.element(linked).toBeChecked();
  await expect.element(linked).toBeEnabled();
  await expect.element(page.getByRole("switch", { name: /Other disabled/ })).toBeDisabled();
  await linked.click();
  expect(onToggle).toHaveBeenCalledTimes(1);

  await page.getByRole("switch", { name: /Other disabled/ }).click({ force: true });
  expect(onToggle).toHaveBeenCalledTimes(1);
});
