import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import WebsiteWebhook from "./WebsiteWebhook.svelte";

const api = vi.hoisted(() => ({ webhook: vi.fn(), rotateWebhookToken: vi.fn() }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ websites: api }) }));

describe("WebsiteWebhook", () => {
  beforeEach(() => {
    api.webhook.mockResolvedValue({
      url: "https://eneo.example/api/v1/webhooks/websites/site/crawl",
      enabled: true,
      pending: true
    });
    api.rotateWebhookToken.mockResolvedValue({
      url: "https://eneo.example/api/v1/webhooks/websites/site/crawl",
      token: "new-secret-token"
    });
  });

  it("shows pending state and reveals a rotated token only in the current view", async () => {
    const view = render(WebsiteWebhook, { websiteId: "site" });
    await expect.element(page.getByText(m.website_webhook_pending())).toBeVisible();
    await expect.element(page.getByText(m.website_webhook_ready())).toBeVisible();
    await page.getByRole("button", { name: m.website_webhook_rotate(), exact: true }).click();
    await expect.element(page.getByText(m.website_webhook_secret())).toBeVisible();
    await expect.element(page.getByText(/Authorization: Bearer new-secret-token/)).toBeVisible();
    expect(api.rotateWebhookToken).toHaveBeenCalledWith({ id: "site" });
    view.unmount();
    render(WebsiteWebhook, { websiteId: "site" });
    await expect.element(page.getByText(m.website_webhook_ready())).toBeVisible();
    await expect
      .element(page.getByText(/Authorization: Bearer new-secret-token/))
      .not.toBeInTheDocument();
  });
});
