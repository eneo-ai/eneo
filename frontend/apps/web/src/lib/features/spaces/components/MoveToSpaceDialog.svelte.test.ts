import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { readable } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({ id: "current" }),
      accessibleSpaces: readable([
        { id: "current", name: "Current space" },
        { id: "target", name: "Target space" }
      ])
    }
  })
}));

import MoveToSpaceDialog from "./MoveToSpaceDialog.svelte";

async function chooseTarget() {
  await page.getByRole("button", { name: m.destination() }).click();
  await expect.element(page.getByRole("option", { name: "Target space" })).toBeVisible();
  expect(page.getByRole("option", { name: "Current space" }).elements()).toHaveLength(0);
  await page.getByRole("option", { name: "Target space" }).click();
}

describe("MoveToSpaceDialog", () => {
  it("moves to the chosen space, never offering the current one", async () => {
    const onMove = vi.fn(() => Promise.resolve());
    render(MoveToSpaceDialog, {
      open: true,
      title: "Move service",
      submitLabel: "Move service",
      hint: "Moving takes a while",
      onMove
    });

    await expect.element(page.getByText("Moving takes a while")).toBeVisible();
    await chooseTarget();
    await page.getByRole("button", { name: "Move service" }).click();

    expect(onMove).toHaveBeenCalledWith({ id: "target" }, { moveResources: false });
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  });

  it("passes the resources switch and shows its hint while it is on", async () => {
    const onMove = vi.fn(() => Promise.resolve());
    render(MoveToSpaceDialog, {
      open: true,
      title: "Move assistant",
      submitLabel: "Move assistant",
      resourcesOption: { label: "Include knowledge", hint: "Knowledge moves too" },
      onMove
    });

    await chooseTarget();
    await expect.element(page.getByText("Knowledge moves too")).not.toBeInTheDocument();
    await page.getByRole("switch", { name: "Include knowledge" }).click();
    await expect.element(page.getByText("Knowledge moves too")).toBeVisible();
    await page.getByRole("button", { name: "Move assistant" }).click();

    expect(onMove).toHaveBeenCalledWith({ id: "target" }, { moveResources: true });
  });
});
