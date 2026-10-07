import type { OutboundHeaderPreview, UserSparse } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import OutboundHeadersPreview from "./OutboundHeadersPreview.svelte";
import "../../../../app.css";

type UserPage = { items: UserSparse[] };

const api = vi.hoisted(() => ({
  list: vi.fn<(request: unknown) => Promise<UserPage>>(),
  previewOutboundHeaders: vi.fn<(...args: unknown[]) => Promise<OutboundHeaderPreview>>(),
  toastError: vi.fn()
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    users: { list: api.list },
    modelProviders: { previewOutboundHeaders: api.previewOutboundHeaders }
  })
}));
vi.mock("$lib/core/errors", () => ({ toastError: api.toastError }));

const user = (email: string) => ({ id: `id-${email}`, email }) as UserSparse;

beforeEach(() => {
  vi.resetAllMocks();
});

const trigger = () =>
  page.getByRole("button", {
    name: `${m.outbound_headers_preview_user()} ${m.outbound_headers_preview_choose_user()}`
  });
const search = () => page.getByLabelText(m.outbound_headers_preview_search());

async function openAndSearch(text: string) {
  await trigger().click();
  await search().fill(text);
}

describe("OutboundHeadersPreview", () => {
  it("previews for a chosen user, with secret headers as status only", async () => {
    api.list.mockResolvedValue({ items: [user("ada@example.com")] });
    api.previewOutboundHeaders.mockResolvedValue({
      user_id: "id-ada@example.com",
      blocked: false,
      destination_problem: null,
      blocked_reason: null,
      headers: [
        { name: "X-Org-Unit", secret: false, state: "resolved", value: "Milj%C3%B6" },
        { name: "X-Credential", secret: true, state: "resolved", value: null }
      ]
    });
    render(OutboundHeadersPreview, { providerId: "p1", hasUnsavedChanges: false });

    await openAndSearch("ada");
    await page.getByRole("option", { name: "ada@example.com" }).click();
    await page.getByRole("button", { name: m.outbound_headers_preview_run() }).click();

    await expect
      .element(page.getByText(m.outbound_headers_preview_sent(), { exact: true }).first())
      .toBeVisible();
    await expect.element(page.getByText("Milj%C3%B6")).toBeVisible();
    await expect.element(page.getByText(m.outbound_headers_preview_secret_hidden())).toBeVisible();
    expect(api.previewOutboundHeaders).toHaveBeenCalledWith(
      { id: "p1" },
      { userId: "id-ada@example.com" }
    );
  });

  it("explains a block that no single header causes", async () => {
    api.list.mockResolvedValue({ items: [user("ada@example.com")] });
    api.previewOutboundHeaders.mockResolvedValue({
      user_id: "id-ada@example.com",
      blocked: true,
      destination_problem: null,
      blocked_reason: "total_size_exceeded",
      headers: []
    });
    render(OutboundHeadersPreview, { providerId: "p1", hasUnsavedChanges: false });

    await openAndSearch("ada");
    await page.getByRole("option", { name: "ada@example.com" }).click();
    await page.getByRole("button", { name: m.outbound_headers_preview_run() }).click();

    await expect.element(page.getByText(m.outbound_headers_reason_total_size())).toBeVisible();
  });

  it("reports a failed search instead of claiming no users exist", async () => {
    api.list.mockRejectedValue(new Error("offline"));
    render(OutboundHeadersPreview, { providerId: "p1", hasUnsavedChanges: false });

    await openAndSearch("ada");

    await expect.element(page.getByText(m.outbound_headers_preview_search_failed())).toBeVisible();
    await expect
      .element(page.getByText(m.outbound_headers_preview_no_users()))
      .not.toBeInTheDocument();
  });

  it("ignores a search response that arrives after a newer one", async () => {
    let resolveOld: (value: UserPage) => void = () => {};
    api.list
      .mockImplementationOnce(() => new Promise((resolve) => (resolveOld = resolve)))
      .mockResolvedValueOnce({ items: [user("new@example.com")] });
    render(OutboundHeadersPreview, { providerId: "p1", hasUnsavedChanges: false });

    await openAndSearch("old");
    await expect.poll(() => api.list.mock.calls.length).toBe(1);
    await search().fill("new");
    await expect.element(page.getByRole("option", { name: "new@example.com" })).toBeVisible();

    resolveOld({ items: [user("old@example.com")] });

    await expect.poll(() => api.list.mock.calls.length).toBe(2);
    await expect
      .element(page.getByRole("option", { name: "old@example.com" }))
      .not.toBeInTheDocument();
    await expect.element(page.getByRole("option", { name: "new@example.com" })).toBeVisible();
  });
});
