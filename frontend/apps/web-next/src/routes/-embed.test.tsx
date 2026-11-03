// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createTranslator } from "use-intl";
import { BootContext } from "@/boot-context";
import { makeQueryClient } from "@/lib/api/query";
import messages from "@/lib/i18n/messages/sv.json";
import { createAppRouter } from "@/router";

// Conversation behavior has component coverage; here the real public routes,
// boot providers and visitor transport must work without an app session.
vi.mock("@/features/widget/components/embed-app", () => ({
  EmbedApp: ({
    config,
    previewToken,
    hostOrigin
  }: {
    config: { name: string };
    previewToken: string | null;
    hostOrigin: string | null;
  }) => (
    <main>
      <h1>{config.name}</h1>
      <p>{previewToken}</p>
      <p>{hostOrigin}</p>
    </main>
  )
}));

const publicId = "wgt_aaaaaaaaaaaaaaaaaaaaaa";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete document.documentElement.dataset.eneoEmbedScheme;
  delete document.documentElement.dataset.eneoEmbedState;
  window.history.replaceState({}, "", "/");
});

async function open(path: string, response: Response) {
  window.history.replaceState({}, "", path);
  document.documentElement.dataset.eneoEmbedScheme = "light";
  const fetcher = vi.fn<typeof fetch>(async () => response.clone());
  vi.stubGlobal("fetch", fetcher);
  const queryClient = makeQueryClient();
  const router = createAppRouter(
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
    { history: createMemoryHistory({ initialEntries: [path] }) }
  );
  render(
    <BootContext value={{ locale: "sv", messages, nonce: undefined }}>
      <RouterProvider router={router} />
    </BootContext>
  );
  await act(() => router.load());
  return { fetcher, router };
}

it.each(["/embed", "/en/embed"])(
  "loads %s directly without a browser-session request or cookie credentials",
  async (prefix) => {
    const { fetcher } = await open(
      `${prefix}/${publicId}?origin=https%3A%2F%2Fkommun.se&scheme=light`,
      Response.json({ name: "Besökschatten", texts: { title: "Besökschatten" } })
    );
    expect(await screen.findByRole("heading", { name: "Besökschatten" })).toBeTruthy();
    expect(screen.getByText("https://kommun.se")).toBeTruthy();
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [input, init] = fetcher.mock.calls[0]!;
    const request = new Request(input, init);
    expect(new URL(request.url).pathname).toBe(`/api/v1/widgets/${publicId}/config/`);
    expect(request.credentials).toBe("omit");
    expect(request.headers.has("authorization")).toBe(false);
  }
);

it("uses a preview token only from the fragment and never makes an anonymous config request first", async () => {
  document.documentElement.dataset.eneoEmbedState = "preview";
  const { fetcher } = await open(
    `/embed/${publicId}?preview=1#preview=draft-secret`,
    Response.json({ name: "Utkast", texts: { title: "Utkast" } })
  );
  expect(await screen.findByRole("heading", { name: "Utkast" })).toBeTruthy();
  expect(screen.getByText("draft-secret")).toBeTruthy();
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [input, init] = fetcher.mock.calls[0]!;
  const request = new Request(input, init);
  expect(request.headers.get("authorization")).toBe("Bearer draft-secret");
  expect(request.credentials).toBe("omit");
  expect(request.url).not.toContain("draft-secret");
});

it.each(["/embed", "/en/embed"])(
  "keeps %s unavailable for the document lifetime even after the widget is activated",
  async (prefix) => {
    document.documentElement.dataset.eneoEmbedState = "unavailable";
    // The API could now succeed after activation; the existing document still
    // has the freely framed unavailable policy and must never load that chat.
    const { fetcher, router } = await open(
      `${prefix}/${publicId}?origin=https%3A%2F%2Funapproved.example`,
      Response.json({ name: "Activated while loading", texts: { title: "Active chat" } })
    );
    expect(
      await screen.findByRole("heading", { name: messages.widget_not_available_title })
    ).toBeTruthy();
    expect(fetcher).not.toHaveBeenCalled();
    await act(() => router.invalidate());
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Activated while loading" })).toBeNull();
  }
);

it("shows a framed unavailable notice for a paused or unknown widget", async () => {
  await open(
    `/embed/${publicId}`,
    Response.json({ detail: { code: "widget_not_active" } }, { status: 404 })
  );
  expect(
    await screen.findByRole("heading", { name: messages.widget_not_available_title })
  ).toBeTruthy();
});
