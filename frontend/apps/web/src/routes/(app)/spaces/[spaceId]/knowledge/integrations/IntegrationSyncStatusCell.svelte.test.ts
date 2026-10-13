import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../../../app.css";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import IntegrationSyncStatusCell from "./IntegrationSyncStatusCell.svelte";

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function knowledge(
  metadata: Partial<Metadata>,
  overrides: Partial<IntegrationKnowledge> = {}
): IntegrationKnowledge {
  return {
    id: "k-1",
    name: "Policies",
    integration_type: "sharepoint",
    metadata: { size: 0, ...metadata },
    ...overrides
  } as IntegrationKnowledge;
}

describe("IntegrationSyncStatusCell", () => {
  it.each([
    ["never", { last_sync_status: "never" }, () => m.integration_sync_status_never()],
    [
      "success",
      { last_sync_status: "success", document_count: 12, last_synced_at: new Date().toISOString() },
      () => m.integration_sync_status_success()
    ],
    [
      "error",
      { last_sync_status: "error", last_sync_error: "Token expired", document_count: 3 },
      () => m.integration_sync_status_error()
    ],
    [
      "empty",
      { last_sync_status: "success", document_count: 0, last_synced_at: new Date().toISOString() },
      () => m.integration_sync_status_empty()
    ]
  ] as const)("shows the %s badge", async (_state, metadata, label) => {
    render(IntegrationSyncStatusCell, { knowledge: knowledge(metadata) });
    await expect.element(page.getByText(label(), { exact: true })).toBeVisible();
  });

  it("shows the document count and the last successful sync", async () => {
    render(IntegrationSyncStatusCell, {
      knowledge: knowledge({
        last_sync_status: "success",
        document_count: 12,
        last_synced_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString()
      })
    });
    await expect
      .element(page.getByText(m.integration_documents_other({ count: 12 })))
      .toBeVisible();
    await expect
      .element(page.getByText(m.integration_last_synced_hours_ago({ hours: 3 })))
      .toBeVisible();
  });

  it("reveals the error text from a keyboard-operable disclosure", async () => {
    render(IntegrationSyncStatusCell, {
      knowledge: knowledge({
        last_sync_status: "error",
        last_sync_error: "AADSTS7000215: Invalid client secret provided.",
        last_sync_attempted_at: new Date().toISOString()
      })
    });
    const trigger = page.getByRole("button", { name: m.integration_sync_error_show() });
    await expect.element(trigger).toHaveAttribute("aria-expanded", "false");
    await expect.element(page.getByText(/AADSTS7000215/)).not.toBeVisible();

    (trigger.element() as HTMLElement).focus();
    await userEvent.keyboard("{Enter}");

    await expect.element(page.getByText(/AADSTS7000215/)).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.integration_sync_error_hide() }))
      .toHaveAttribute("aria-expanded", "true");
  });

  it("aggregates a wrapper: an error names the failed item, otherwise documents add up", async () => {
    const { unmount } = render(IntegrationSyncStatusCell, {
      knowledge: [
        knowledge({ last_sync_status: "success", document_count: 5 }, { id: "a", name: "A" }),
        knowledge(
          { last_sync_status: "error", last_sync_error: "403 Forbidden", document_count: 1 },
          { id: "b", name: "Archive" }
        )
      ]
    });
    await expect
      .element(page.getByText(m.integration_sync_status_error(), { exact: true }))
      .toBeVisible();
    await page.getByRole("button", { name: m.integration_sync_error_show() }).click();
    await expect.element(page.getByText("Archive:")).toBeVisible();
    await expect.element(page.getByText("403 Forbidden")).toBeVisible();
    unmount();

    render(IntegrationSyncStatusCell, {
      knowledge: [
        knowledge({ last_sync_status: "success", document_count: 5 }, { id: "a", name: "A" }),
        knowledge({ last_sync_status: "success", document_count: 7 }, { id: "b", name: "B" })
      ]
    });
    await expect
      .element(page.getByText(m.integration_documents_other({ count: 12 })))
      .toBeVisible();
    expect(page.getByRole("button", { name: m.integration_sync_error_show() }).query()).toBeNull();
  });

  it("opens the sync history from the timeline button", async () => {
    const onShowSyncHistory = vi.fn();
    render(IntegrationSyncStatusCell, {
      knowledge: knowledge({ last_sync_status: "success", document_count: 2 }),
      onShowSyncHistory
    });
    await page.getByRole("button", { name: new RegExp(m.sync_history()) }).click();
    expect(onShowSyncHistory).toHaveBeenCalledOnce();
  });

  it("exposes the webhook explanation to keyboard and screen-reader users", async () => {
    render(IntegrationSyncStatusCell, {
      knowledge: knowledge({ last_sync_status: "success", document_count: 2 })
    });
    const trigger = page.getByRole("button", {
      name: new RegExp(m.sharepoint_webhook_none_tooltip())
    });
    await expect.element(trigger).toBeVisible();
    expect((trigger.element() as HTMLElement).tabIndex).toBe(0);

    await userEvent.keyboard("{Tab}");
    expect(document.activeElement).toBe(trigger.element());
    await vi.waitFor(() =>
      expect(document.querySelector("[data-tooltip-content]")).toHaveTextContent(
        m.sharepoint_webhook_none_tooltip()
      )
    );
    expect(trigger.element().hasAttribute("aria-describedby")).toBe(false);
  });

  it("has no axe violations in the error state", async () => {
    const { container } = render(IntegrationSyncStatusCell, {
      knowledge: knowledge({
        last_sync_status: "error",
        last_sync_error: "Token expired",
        sharepoint_subscription_expires_at: new Date(Date.now() + 10 * 3600 * 1000).toISOString()
      }),
      onShowSyncHistory: vi.fn()
    });
    await page.getByRole("button", { name: m.integration_sync_error_show() }).click();
    await expectNoAxeViolations(container);
  });
});
