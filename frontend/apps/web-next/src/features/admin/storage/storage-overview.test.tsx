// @vitest-environment jsdom
import { screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { StorageOverview } from "./storage-overview";

it.each(["ready", "object_store_not_configured", "store_degraded", undefined] as const)(
  "shows object storage availability for %s and links to setup when unavailable",
  async (readiness) => {
    const capability: Schema<"CapabilityPublic"> | undefined = readiness
      ? {
          target: "object_store",
          maximum_bytes: null,
          configured: readiness !== "object_store_not_configured",
          selectable: readiness === "ready",
          readiness_code: readiness
        }
      : undefined;
    renderInApp(
      <StorageOverview
        inventory={null}
        inventoryLoading={false}
        inventoryError={false}
        moves={null}
        movesLoading={false}
        movesError={false}
        activeTarget="postgres_inline"
        objectStoreCapability={capability}
        onInventoryRetry={vi.fn()}
      />
    );
    const card = screen
      .getByText("Objektlagring", { selector: "[data-slot=card-title]" })
      .closest<HTMLElement>("[data-slot=card]");
    if (!card) throw new Error("Object storage card missing");
    expect(
      within(card).getByText(readiness === "ready" ? "Redo att användas" : "Otillgänglig", {
        selector: "[data-slot=badge]"
      })
    ).toBeTruthy();
    const guide = within(card).queryByRole("link", { name: "Läs guiden om objektlagring" });
    if (readiness === "ready") expect(guide).toBeNull();
    else
      expect(guide?.getAttribute("href")).toBe(
        "https://docs.eneo.ai/guides/object-content-storage"
      );
    await expectNoAxeViolations(card);
  }
);
