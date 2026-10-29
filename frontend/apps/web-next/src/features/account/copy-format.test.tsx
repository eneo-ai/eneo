// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { QueryAppContextProvider } from "@/components/providers/app-context-from-queries";
import { browserApi } from "@/lib/api/browser";
import { loadSession } from "@/lib/api/session";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { CopyFormatChoice, useCopyFormatLabel } from "./copy-format";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const context = testAppContext({ settings: { whats_new_enabled: false } });
let settings = context.settings;

beforeEach(() => {
  vi.clearAllMocks();
  settings = context.settings;
  const replies = new Map<string, unknown>([
    ["/api/v1/users/me/", context.user],
    ["/api/v1/users/tenant/", context.tenant],
    ["/api/v1/auth/federation-status", context.federationStatus],
    ["/api/v1/limits/", context.limits],
    ["/api/v1/whats-new/state/", null]
  ]);
  api.GET.mockImplementation(async (path: string) => ({
    data: path === "/api/v1/settings/" ? settings : replies.get(path),
    response: new Response(null, { status: 200 })
  }));
  api.POST.mockImplementation(async (_path, { body }) => {
    settings = body;
    return { data: settings, response: new Response(null, { status: 200 }) };
  });
});

function SavedFormat() {
  return <output>{useCopyFormatLabel()}</output>;
}

async function renderChoice() {
  const queryClient = testQueryClient();
  await loadSession(queryClient, browserApi);
  renderInApp(
    <QueryAppContextProvider
      env={{ links: context.links, frontendVersion: "1", backendVersion: "1" }}
    >
      <CopyFormatChoice />
      <SavedFormat />
    </QueryAppContextProvider>,
    { queryClient }
  );
}

it("refreshes the saved format for other app-context readers without a document refresh", async () => {
  await renderChoice();
  expect(screen.getByRole("status").textContent).toBe(messages.copy_format_markdown);
  fireEvent.click(screen.getByRole("radio", { name: messages.copy_format_richtext }));
  await waitFor(() =>
    expect(screen.getByRole("status").textContent).toBe(messages.copy_format_richtext)
  );
  expect(api.POST).toHaveBeenCalledTimes(1);
});

it("restores the selected format and leaves other readers unchanged when saving fails", async () => {
  await renderChoice();
  api.POST.mockResolvedValueOnce({
    error: { message: "Unavailable" },
    response: new Response(null, { status: 503 })
  });
  fireEvent.click(screen.getByRole("radio", { name: messages.copy_format_richtext }));
  await waitFor(() =>
    expect(
      screen.getByRole("radio", { name: messages.copy_format_markdown }).getAttribute("data-state")
    ).toBe("checked")
  );
  expect(screen.getByRole("status").textContent).toBe(messages.copy_format_markdown);
});
