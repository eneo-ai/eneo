// @vitest-environment jsdom
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createTranslator } from "use-intl";
import {
  Profiler,
  useState,
  type ComponentProps,
  type ProfilerOnRenderCallback,
  type ReactNode
} from "react";
import type { ChatPage } from "@/features/chat/chat-page";
import type { Schema } from "@/lib/api/models";
import messages from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";
import {
  makeCollection,
  makeIntegration,
  makeSpace,
  makeWebsite
} from "@/features/spaces/testing/space-fixture";
import type { ItemDetail } from "@/features/knowledge/integrations/item-detail.client";
import type { WrapperDetail } from "@/features/knowledge/integrations/wrapper-detail.client";
import type { KnowledgePage } from "@/features/knowledge/knowledge-page";
import type { WebsiteDetail } from "@/features/knowledge/detail/website-detail.client";
import { setViewport } from "@/test/setup-dom";

vi.unmock("@/lib/link");

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/navigate-to", () => ({ navigateTo: navigate }));
// These features own polling/tour tests; this suite exercises the route and session boundary.
vi.mock("@/features/jobs/use-jobs", () => ({
  JobsProvider: ({ children }: { children: ReactNode }) => children,
  useJobs: () => ({ trackJob: vi.fn() })
}));
vi.mock("@/features/whats-new/tour-provider", () => ({
  TourProvider: ({ children }: { children: ReactNode }) => children,
  useTour: () => ({ running: false, start: vi.fn() })
}));
vi.mock("@/components/shell/notification-bells", () => ({ NotificationBells: () => null }));
vi.mock("@/features/admin/federation/federation-page", () => ({
  FederationPage: () => <h1>{messages.federation_admin_title}</h1>
}));

const GENERATION = "Eneo-Session-Generation";
const context = testAppContext({ settings: { whats_new_enabled: false } });
let replies: Map<string, unknown>;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

function EditorDraft({ id }: { id: string }) {
  const [draft, setDraft] = useState("");
  return (
    <input
      aria-label={`Editor ${id}`}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
    />
  );
}

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  // The router scrolls the main panel; jsdom has no element scrolling implementation.
  HTMLElement.prototype.scrollTo = () => {};
  window.history.replaceState({}, "", "/does-not-exist");
  document.cookie = "eneo_sidenav_collapsed=; Path=/; Max-Age=0";
  replies = new Map<string, unknown>([
    ["/api/v1/users/me/", context.user],
    ["/api/v1/users/tenant/", context.tenant],
    ["/api/v1/settings/", context.settings],
    ["/api/v1/auth/federation-status", context.federationStatus],
    ["/api/v1/limits/", context.limits],
    ["/api/v1/whats-new/state/", { seen_version: null, announced_version: null }],
    ["/api/v1/spaces/", { items: [] }],
    ["/api/v1/spaces/type/personal/", makeSpace({ overrides: { personal: true } })]
  ]);
  fetcher = vi.fn<typeof fetch>(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    const headers = new Headers({ "content-type": "application/json" });
    // Public discovery does not authenticate a session or emit its generation.
    if (url.pathname !== "/api/v1/auth/federation-status")
      headers.set(GENERATION, "document-session");
    if (url.pathname === "/api/v1/auth/session/")
      return new Response(null, { status: 204, headers });
    if (!replies.has(url.pathname)) throw new Error(`Unexpected request: ${url.pathname}`);
    const reply = await replies.get(url.pathname);
    return reply instanceof Response
      ? reply.clone()
      : new Response(JSON.stringify(reply), { headers });
  });
  vi.stubGlobal("fetch", fetcher);
  // Knowledge feature tests own rendering; these expose the route's loaded data and runtime props.
  vi.doMock("@/features/knowledge/integrations/item-detail.client", () => ({
    ItemDetail: ({ itemId, loaded }: ComponentProps<typeof ItemDetail>) => (
      <section aria-label={`Item ${itemId}`}>
        <pre>{JSON.stringify(loaded.items)}</pre>
      </section>
    )
  }));
  vi.doMock("@/features/knowledge/integrations/wrapper-detail.client", () => ({
    WrapperDetail: ({ wrapperId, loaded }: ComponentProps<typeof WrapperDetail>) => (
      <section aria-label={`Wrapper ${wrapperId}`}>
        <pre>{JSON.stringify(loaded.items)}</pre>
      </section>
    )
  }));
  vi.doMock("@/features/knowledge/knowledge-page", () => ({
    KnowledgePage: ({ integrationRequestFormUrl }: ComponentProps<typeof KnowledgePage>) => (
      <h1>{integrationRequestFormUrl ?? "Knowledge hub"}</h1>
    )
  }));
  vi.doMock("@/features/knowledge/detail/website-detail.client", () => ({
    WebsiteDetail: ({
      websiteId,
      integrationRequestFormUrl
    }: ComponentProps<typeof WebsiteDetail>) => (
      <section aria-label={`Website ${websiteId}`}>{integrationRequestFormUrl}</section>
    )
  }));
  // Editor fields have feature tests; here their local state exposes the route's identity boundary.
  vi.doMock("@/features/apps/editor/app-editor", () => ({
    AppEditor: ({ appId }: { appId: string }) => <EditorDraft id={appId} />
  }));
  vi.doMock("@/features/assistants/editor/assistant-editor", () => ({
    AssistantEditor: ({ assistantId }: { assistantId: string }) => <EditorDraft id={assistantId} />
  }));
  vi.doMock("@/features/group-chats/group-chat-editor", () => ({
    GroupChatEditor: ({ groupChatId }: { groupChatId: string }) => <EditorDraft id={groupChatId} />
  }));
  // Chat streaming has its own feature and browser tests; keep its state observable here.
  vi.doMock("@/features/chat/chat-page", async () => {
    const { replaceUrl } = await import("@/lib/navigation");
    return {
      ChatPage: ({
        sessionId,
        buildSessionUrl
      }: Required<Pick<ComponentProps<typeof ChatPage>, "sessionId" | "buildSessionUrl">>) => {
        const [answers, setAnswers] = useState(0);
        const [draft, setDraft] = useState("");
        return (
          <>
            <input
              aria-label="Draft"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <button
              onClick={() => {
                setAnswers((count) => count + 1);
                replaceUrl(buildSessionUrl("saved-session"));
              }}
            >
              Chat {sessionId ?? "new"}: {answers}
            </button>
          </>
        );
      }
    };
  });
  vi.doMock("@/lib/api/base", async () => ({
    ...(await vi.importActual<typeof import("@/lib/api/base")>("@/lib/api/base")),
    // Node's Request needs an absolute base; response/session middleware stays real.
    API_BASE: window.location.origin
  }));
  // Transform the app graph during fixture setup, outside each behavior assertion's timeout.
  await import("@/router");
});

it("opens the knowledge hub and passes the operator's runtime integration form URL", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  const { runtimeConfig, setRuntimeConfig } = await import("@/lib/runtime-config");
  await renderRoute("/spaces/space-1/knowledge", undefined, () => {
    setRuntimeConfig({
      ...runtimeConfig(),
      request_integration_form_url: "https://forms.example.test/request"
    });
  });
  await screen.findByRole("heading", { name: "https://forms.example.test/request" });
  expect(document.title).toBe(`${messages.knowledge} · Upphandling · Eneo`);
});

it("redirects the integration index to the knowledge tab", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  const { router } = await renderRoute("/spaces/space-1/knowledge/integrations");
  expect(router.state.location.pathname).toBe("/spaces/space-1/knowledge");
  expect(router.state.location.search).toEqual({ tab: "integrations" });
  await screen.findByRole("heading", { name: "Knowledge hub" });
});

it("loads a standalone integration and its title from one space request", async () => {
  const item = makeIntegration({ id: "item-1", name: "Avtal" });
  replies.set("/api/v1/spaces/space-1/", makeSpace({ integrations: [item] }));
  const { router } = await renderRoute(
    "/spaces/space-1/knowledge/integrations/item-1",
    undefined,
    ({ queryClient }) => {
      queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    }
  );
  const view = await screen.findByRole("region", { name: "Item item-1" });
  expect(JSON.parse(view.textContent!)).toEqual([item]);
  expect(document.title).toBe("Avtal · Upphandling · Eneo");
  await act(() =>
    router.navigate({ href: "/spaces/space-1/knowledge/integrations/item-1?tab=activity" })
  );
  expect(screen.getByRole("region", { name: "Item item-1" })).toBe(view);
  expect(requestedPaths().filter((path) => path === "/api/v1/spaces/space-1/")).toHaveLength(1);
});

it.each([
  ["skipped", "problems"],
  ["activity", "activity"],
  ["unknown", undefined],
  ["content&tab=activity", undefined]
])(
  "redirects a wrapped SharePoint item with tab=%s through the shared parser",
  async (tab, expectedTab) => {
    const item = makeIntegration({
      id: "item-1",
      wrapper_id: "wrapper-1",
      wrapper_name: "Byggnad"
    });
    replies.set("/api/v1/spaces/space-1/", makeSpace({ integrations: [item] }));
    const { router } = await renderRoute(
      `/spaces/space-1/knowledge/integrations/item-1?tab=${tab}`,
      undefined,
      ({ queryClient }) => {
        queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
      }
    );
    expect(router.state.location.pathname).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/wrapper-1"
    );
    expect(router.state.location.search).toEqual({
      folder: "item-1",
      ...(expectedTab && { tab: expectedTab })
    });
    const view = await screen.findByRole("region", { name: "Wrapper wrapper-1" });
    expect(JSON.parse(view.textContent!)).toEqual([item]);
    expect(document.title).toBe("Byggnad · Upphandling · Eneo");
    expect(requestedPaths().filter((path) => path === "/api/v1/spaces/space-1/")).toHaveLength(1);
  }
);

it.each(["missing", "foreign", "wrapper/missing", "wrapper/foreign"])(
  "does not open unknown or foreign integration sources: %s",
  async (path) => {
    replies.set(
      "/api/v1/spaces/space-1/",
      makeSpace({
        integrations: [
          makeIntegration({ id: "owned", wrapper_id: "owned" }),
          makeIntegration({ id: "foreign", wrapper_id: "foreign", space_id: "space-2" })
        ]
      })
    );
    await renderRoute(`/spaces/space-1/knowledge/integrations/${path}`);
    await screen.findByRole("heading", { name: messages.page_not_found });
    expect(requestedPaths()).toContain("/api/v1/spaces/space-1/");
  }
);

it("excludes shared items from a wrapper and uses the space alias in source links", async () => {
  const owned = makeIntegration({
    id: "owned",
    wrapper_id: "wrapper-1",
    wrapper_name: "Egen källa"
  });
  replies.set(
    "/api/v1/spaces/type/personal/",
    makeSpace({
      integrations: [
        owned,
        makeIntegration({ id: "foreign", wrapper_id: "wrapper-1", space_id: "space-2" })
      ],
      overrides: { personal: true }
    })
  );
  const { router } = await renderRoute("/spaces/personal/knowledge/integrations/owned");
  expect(router.state.location.pathname).toBe(
    "/spaces/personal/knowledge/integrations/wrapper/wrapper-1"
  );
  const view = await screen.findByRole("region", { name: "Wrapper wrapper-1" });
  expect(JSON.parse(view.textContent!)).toEqual([owned]);
  expect(document.title).toBe(`Egen källa · ${messages.personal} · Eneo`);
});

it.each([
  { source: "item-1", status: 404 },
  { source: "wrapper/wrapper-1", status: 404 },
  { source: "item-1", status: 500 },
  { source: "wrapper/wrapper-1", status: 500 }
])(
  "preserves the space's $status failure for $source without another request",
  async ({ source, status }) => {
    replies.set("/api/v1/spaces/missing/", new Response(null, { status }));
    await renderRoute(`/spaces/missing/knowledge/integrations/${source}`);
    await screen.findByRole("heading", {
      name: status === 404 ? messages.page_not_found : messages.something_went_wrong
    });
    expect(requestedPaths().filter((path) => path === "/api/v1/spaces/missing/")).toHaveLength(1);
  }
);

it("checks integration ownership against the parent's refreshed space on a return visit", async () => {
  const item = makeIntegration({ id: "item-1", name: "Old source" });
  replies.set("/api/v1/spaces/space-1/", makeSpace({ integrations: [item] }));
  const href = "/spaces/space-1/knowledge/integrations/item-1";
  const { router, queryClient } = await renderRoute(href, undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  });
  await screen.findByRole("region", { name: "Item item-1" });
  await act(() => router.navigate({ href: "/account" }));
  let release!: (space: ReturnType<typeof makeSpace>) => void;
  replies.set(
    "/api/v1/spaces/space-1/",
    new Promise((resolve) => {
      release = resolve;
    })
  );
  await queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"], refetchType: "none" });
  let navigation!: Promise<void>;
  try {
    await act(async () => {
      navigation = router.navigate({ href });
    });
    expect(screen.queryByRole("region", { name: "Item item-1" })).toBeNull();
  } finally {
    await act(async () => {
      release(makeSpace({ integrations: [makeIntegration({ ...item, space_id: "space-2" })] }));
      await navigation;
    });
  }
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(screen.queryByRole("region", { name: "Item item-1" })).toBeNull();
});

it.each(["item-1", "wrapper/wrapper-1"])(
  "refreshes ownership when entering %s while the space parent stays mounted",
  async (source) => {
    const item = makeIntegration({
      id: "item-1",
      wrapper_id: source.startsWith("wrapper/") ? "wrapper-1" : null
    });
    replies.set("/api/v1/spaces/space-1/", makeSpace({ integrations: [item] }));
    const { router, queryClient } = await renderRoute(
      "/spaces/space-1/knowledge",
      undefined,
      ({ queryClient }) => {
        queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
      }
    );
    await screen.findByRole("heading", { name: "Knowledge hub" });
    let release!: (space: ReturnType<typeof makeSpace>) => void;
    replies.set(
      "/api/v1/spaces/space-1/",
      new Promise((resolve) => {
        release = resolve;
      })
    );
    await queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"], refetchType: "none" });
    let complete = false;
    let navigation!: Promise<void>;
    try {
      await act(async () => {
        navigation = router.navigate({ href: `/spaces/space-1/knowledge/integrations/${source}` });
        void navigation.then(() => {
          complete = true;
        });
      });
      expect(complete).toBe(false);
      expect(screen.queryByRole("region", { name: /^(Item|Wrapper) / })).toBeNull();
    } finally {
      await act(async () => {
        release(makeSpace({ integrations: [makeIntegration({ ...item, space_id: "space-2" })] }));
        await navigation;
      });
    }
    await screen.findByRole("heading", { name: messages.page_not_found });
    expect(requestedPaths().filter((path) => path === "/api/v1/spaces/space-1/")).toHaveLength(2);
  }
);

it("opens a collection with its prefetched files and resource title", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  replies.set("/api/v1/groups/collection-1/", makeCollection({ permissions: ["read"] }));
  replies.set("/api/v1/groups/collection-1/info-blobs/", { items: [] });
  const { queryClient } = await renderRoute("/spaces/space-1/knowledge/collections/collection-1");
  await screen.findByRole("heading", { name: "Upphandlingspolicy", level: 1 });
  expect(queryClient.getQueryData(["collections", "collection-1", "info-blobs"])).toEqual([]);
  expect(document.title).toBe("Upphandlingspolicy · Upphandling · Eneo");
});

it("opens a website with both paginated lists cached and the runtime form URL", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  replies.set(
    "/api/v1/websites/website-1/",
    makeWebsite({ url: "https://example.test", name: null })
  );
  replies.set("/api/v1/websites/website-1/runs/latest/", null);
  const page = { items: [], next_cursor: null, total_count: 0 };
  replies.set("/api/v1/websites/website-1/runs/", page);
  replies.set("/api/v1/websites/website-1/info-blobs/page/", page);
  const { runtimeConfig, setRuntimeConfig } = await import("@/lib/runtime-config");
  const { queryClient } = await renderRoute(
    "/spaces/space-1/knowledge/websites/website-1",
    undefined,
    () => {
      setRuntimeConfig({
        ...runtimeConfig(),
        request_integration_form_url: "https://forms.example.test/request"
      });
    }
  );
  const view = await screen.findByRole("region", { name: "Website website-1" });
  expect(view.textContent).toBe("https://forms.example.test/request");
  expect(document.title).toBe("example.test · Upphandling · Eneo");
  expect(queryClient.getQueryData(["websites", "website-1", "crawl-runs", "latest"])).toBeNull();
  for (const key of [
    ["crawl-runs", "pages"],
    ["info-blobs", "pages"]
  ])
    expect(queryClient.getQueryData(["websites", "website-1", ...key])).toMatchObject({
      pages: [page]
    });
});

it.each([
  ["collections/missing", "/api/v1/groups/missing/"],
  ["websites/missing", "/api/v1/websites/missing/"]
])("does not open a missing knowledge resource: %s", async (path, apiPath) => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  replies.set(apiPath, new Response(null, { status: 404 }));
  replies.set("/api/v1/groups/missing/info-blobs/", { items: [] });
  replies.set("/api/v1/websites/missing/runs/latest/", null);
  replies.set("/api/v1/websites/missing/runs/", { items: [] });
  replies.set("/api/v1/websites/missing/info-blobs/page/", { items: [] });
  await renderRoute(`/spaces/space-1/knowledge/${path}`);
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(requestedPaths()).toContain(apiPath);
});

it.each(["assistants", "apps", "services"] as const)(
  "opens the space %s list with its space title",
  async (kind) => {
    replies.set("/api/v1/spaces/space-1/", makeSpace({ resourcePermissions: [] }));
    await renderRoute(`/spaces/space-1/${kind}`);
    await screen.findByRole("heading", { name: messages[kind], level: 2 });
    expect(document.title).toBe(`${messages[kind]} · Upphandling · Eneo`);
  }
);

it.each(["apps", "assistants", "group-chats"] as const)(
  "keeps the %s editor draft across section navigation and resets it for another resource",
  async (kind) => {
    replies.set("/api/v1/spaces/space-1/", makeSpace());
    for (const id of ["resource-1", "resource-2"])
      replies.set(`/api/v1/${kind}/${id}/`, { id, name: `Name ${id}` });
    replies.set("/api/v1/help-assistants/availability", new Response(null, { status: 500 }));
    const base = `/spaces/space-1/${kind}`;
    const { router } = await renderRoute(
      `${base}/resource-1/edit`,
      undefined,
      ({ queryClient }) => {
        queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
      }
    );
    const input = await screen.findByRole("textbox", { name: "Editor resource-1" });
    const t = createTranslator({ locale: "sv", messages });
    expect(document.title).toBe(
      `${t("space_edit_title", { name: "Name resource-1" })} · Upphandling · Eneo`
    );
    fireEvent.change(input, { target: { value: "Unfinished instructions" } });
    await act(() => router.navigate({ href: `${base}/resource-1/edit?section=instructions` }));
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Editor resource-1" }).value).toBe(
      "Unfinished instructions"
    );
    expect(requestedPaths().filter((path) => path === `/api/v1/${kind}/resource-1/`)).toHaveLength(
      1
    );
    await act(() => router.navigate({ href: `${base}/resource-2/edit` }));
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Editor resource-2" }).value).toBe(
      ""
    );
  }
);

it.each([
  { admin: true, destination: "/admin/help-assistants" },
  { admin: false, destination: "/spaces/personal/chat" }
])(
  "redirects a help assistant through destination access (admin=$admin)",
  async ({ admin, destination }) => {
    replies.set("/api/v1/users/me/", testAppContext({ permissions: admin ? ["admin"] : [] }).user);
    replies.set("/api/v1/spaces/space-1/", makeSpace());
    replies.set("/api/v1/assistants/help/", { id: "help", name: "Guide", is_help_assistant: true });
    replies.set("/api/v1/admin/help-assistants/roles/", { items: [] });
    replies.set("/api/v1/admin/help-assistants/templates/", { items: [] });
    const { router } = await renderRoute("/spaces/space-1/assistants/help/edit");
    await waitFor(() => expect(router.state.location.pathname).toBe(destination));
    expect(screen.queryByRole("textbox", { name: "Editor help" })).toBeNull();
    expect(requestedPaths()).not.toContain("/api/v1/help-assistants/availability");
    if (admin) {
      await screen.findByRole("heading", {
        name: messages.admin_help_assistants_page_title,
        level: 1
      });
    } else {
      expect(requestedPaths()).not.toContain("/api/v1/admin/help-assistants/roles/");
    }
  }
);

it.each([
  ["apps/missing", "/api/v1/apps/missing/"],
  ["group-chats/missing/edit", "/api/v1/group-chats/missing/"],
  ["services/missing", "/api/v1/services/missing/"]
])("maps a missing space resource %s to not-found after reading it", async (path, apiPath) => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  replies.set(apiPath, new Response(null, { status: 404 }));
  replies.set("/api/v1/apps/missing/runs/", { items: [] });
  await renderRoute(`/spaces/space-1/${path}`);
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(requestedPaths()).toContain(apiPath);
});

it("shows a resource load failure through the route error boundary", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  replies.set("/api/v1/services/failed/", new Response(null, { status: 500 }));
  await renderRoute("/spaces/space-1/services/failed");
  await screen.findByRole("heading", { name: messages.something_went_wrong });
  expect(screen.queryByRole("heading", { name: messages.page_not_found })).toBeNull();
});

it("awaits a fresh existence check when returning to an invalidated service", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  replies.set("/api/v1/services/service-1/", {
    id: "service-1",
    name: "Old service",
    permissions: []
  });
  const href = "/spaces/space-1/services/service-1";
  const { router, queryClient } = await renderRoute(href, undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  });
  await screen.findByRole("heading", { name: "Old service", level: 1 });
  await act(() => router.navigate({ href: "/account" }));
  let release!: (response: Response) => void;
  replies.set(
    "/api/v1/services/service-1/",
    new Promise<Response>((resolve) => {
      release = resolve;
    })
  );
  await queryClient.invalidateQueries({ queryKey: ["services", "service-1"], refetchType: "none" });
  let complete = false;
  let navigation!: Promise<void>;
  try {
    await act(async () => {
      navigation = router.navigate({ href });
      void navigation.then(() => {
        complete = true;
      });
    });
    expect(complete).toBe(false);
    expect(screen.queryByRole("heading", { name: "Old service", level: 1 })).toBeNull();
  } finally {
    await act(async () => {
      release(new Response(null, { status: 404 }));
      await navigation;
    });
  }
  await screen.findByRole("heading", { name: messages.page_not_found });
});

it("keeps a space app's URL tab and resets its run input for a different app", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  for (const id of ["app-1", "app-2"]) {
    replies.set(`/api/v1/apps/${id}/`, {
      ...dashboardApp,
      id,
      name: id,
      input_fields: [{ type: "text-field" }],
      permissions: []
    });
    replies.set(`/api/v1/apps/${id}/runs/`, { items: [] });
  }
  const { router } = await renderRoute(
    "/spaces/space-1/apps/app-1?tab=results",
    undefined,
    ({ queryClient }) => {
      queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    }
  );
  await screen.findByRole("heading", { name: "app-1", level: 1 });
  expect(screen.getByRole("tab", { name: messages.results }).getAttribute("aria-selected")).toBe(
    "true"
  );
  expect(document.title).toBe("app-1 · Upphandling · Eneo");
  await act(() => router.navigate({ href: "/spaces/space-1/apps/app-1?tab=run" }));
  const input = await screen.findByRole("textbox", { name: messages.enter_your_question_here });
  fireEvent.change(input, { target: { value: "First app's input" } });
  expect(requestedPaths().filter((path) => path === "/api/v1/apps/app-1/")).toHaveLength(1);
  await act(() => router.navigate({ href: "/spaces/space-1/apps/app-2" }));
  expect(
    screen.getByRole<HTMLTextAreaElement>("textbox", { name: messages.enter_your_question_here })
      .value
  ).toBe("");
});

it.each([false, true])(
  "shows a space result's edit link only with edit permission (%s)",
  async (canEdit) => {
    setViewport("desktop");
    replies.set("/api/v1/spaces/space-1/", makeSpace());
    replies.set("/api/v1/apps/app-1/", { ...dashboardApp, permissions: canEdit ? ["edit"] : [] });
    replies.set("/api/v1/app-runs/run-1/", {
      id: "run-1",
      status: "complete",
      input: { text: "Question", files: [] },
      output: "Result",
      finished_at: "2026-10-30T08:00:00Z",
      user: { id: "user-1", email: "test@example.se" },
      skill_provenance: []
    });
    await renderRoute("/spaces/space-1/apps/app-1/results/run-1");
    await screen.findByText("Result");
    const edit = screen.queryByRole("link", { name: messages.edit });
    expect(edit?.getAttribute("href") ?? null).toBe(
      canEdit ? "/spaces/space-1/apps/app-1/edit" : null
    );
    const t = createTranslator({ locale: "sv", messages });
    expect(document.title).toBe(
      `${t("space_app_result_title", { name: dashboardApp.name })} · Upphandling · Eneo`
    );
  }
);

it("keeps a service without edit permission in its playground and isolates its input", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  for (const id of ["service-1", "service-2"])
    replies.set(`/api/v1/services/${id}/`, { id, name: id, permissions: [] });
  const { router } = await renderRoute("/spaces/space-1/services/service-1?tab=settings");
  const input = await screen.findByRole("textbox", { name: messages.input });
  expect(screen.queryByRole("tab", { name: messages.settings })).toBeNull();
  expect(document.title).toBe("service-1 · Upphandling · Eneo");
  fireEvent.change(input, { target: { value: "First service's input" } });
  await act(() => router.navigate({ href: "/spaces/space-1/services/service-2" }));
  expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: messages.input }).value).toBe("");
});

it("opens the dashboard catalog with its title and existing app links", async () => {
  replies.set("/api/v1/dashboard/", {
    spaces: { items: [makeSpace({ apps: [{ id: "app-1", name: "Avtalsanalys" }] })] }
  });
  await renderRoute("/dashboard");
  await screen.findByRole("heading", { name: messages.assistants, level: 1 });
  await waitFor(() => expect(document.title).toBe(`${messages.assistants} · Eneo`));
  expect(screen.getByRole("link", { name: /Avtalsanalys/ }).getAttribute("href")).toBe(
    "/dashboard/app/app-1"
  );
});

it("shows a failed dashboard load and recovers through the route retry", async () => {
  replies.set(
    "/api/v1/dashboard/",
    new Response("Unavailable", { status: 500, headers: { [GENERATION]: "document-session" } })
  );
  await renderRoute("/dashboard");
  await screen.findByRole("heading", { name: messages.something_went_wrong });
  expect(screen.queryByRole("heading", { name: messages.page_not_found })).toBeNull();
  replies.set("/api/v1/dashboard/", { spaces: { items: [] } });
  fireEvent.click(screen.getByRole("button", { name: messages.try_again }));
  await screen.findByRole("heading", { name: messages.assistants, level: 1 });
});

it.each(["", "/session-1"])(
  "opens dashboard chat%s and preserves chat state when a session is saved",
  async (suffix) => {
    replies.set("/api/v1/assistants/assistant-1/", {
      id: "assistant-1",
      name: "Upphandlingsassistenten",
      groups: [],
      websites: [],
      integration_knowledge_list: [],
      mcp_servers: [],
      enabled_capabilities: [],
      available_capabilities: []
    });
    const { router } = await renderRoute(
      `/dashboard/assistant-1${suffix}`,
      undefined,
      ({ queryClient }) => {
        queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
      }
    );
    const button = await screen.findByRole("button", {
      name: `Chat ${suffix ? "session-1" : "new"}: 0`
    });
    fireEvent.click(button);
    await screen.findByRole("button", { name: "Chat saved-session: 1" });
    expect(router.state.location.pathname).toBe("/dashboard/assistant-1/saved-session");
    expect(
      requestedPaths().filter((path) => path === "/api/v1/assistants/assistant-1/")
    ).toHaveLength(1);
    expect(document.title).toBe("Eneo");
  }
);

it("clears the draft when switching to another cached dashboard assistant", async () => {
  const { router } = await renderRoute("/dashboard/assistant-1", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    for (const id of ["assistant-1", "assistant-2"]) {
      queryClient.setQueryData(["assistants", id], {
        id,
        name: id,
        groups: [],
        websites: [],
        integration_knowledge_list: [],
        mcp_servers: [],
        enabled_capabilities: [],
        available_capabilities: []
      });
    }
  });
  const draft = await screen.findByRole("textbox", { name: "Draft" });
  fireEvent.change(draft, { target: { value: "Question for the first assistant" } });
  await act(() => router.navigate({ href: "/dashboard/assistant-2" }));
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Draft" }).value).toBe("");
  expect(requestedPaths().some((path) => path.startsWith("/api/v1/assistants/"))).toBe(false);
});

it("rejects extra dashboard session segments without loading an assistant", async () => {
  await renderRoute("/dashboard/assistant-1/session-1/extra");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(requestedPaths().some((path) => path.startsWith("/api/v1/assistants/"))).toBe(false);
});

const dashboardApp = {
  id: "app-1",
  name: "Avtalsanalys",
  input_fields: [],
  completion_model: { id: "model-1", name: "Testmodell" }
};

it("clears an app's run input when navigating to a different app", async () => {
  for (const id of ["app-1", "app-2"]) {
    replies.set(`/api/v1/apps/${id}/`, {
      ...dashboardApp,
      id,
      name: id,
      input_fields: [{ type: "text-field" }]
    });
    replies.set(`/api/v1/apps/${id}/runs/`, { items: [] });
  }
  const { router } = await renderRoute("/dashboard/app/app-1");
  const input = await screen.findByRole("textbox", { name: messages.enter_your_question_here });
  fireEvent.change(input, { target: { value: "Fråga till första appen" } });
  await act(() => router.navigate({ href: "/dashboard/app/app-2" }));
  await screen.findByRole("heading", { name: "app-2", level: 1 });
  expect(
    screen.getByRole<HTMLTextAreaElement>("textbox", { name: messages.enter_your_question_here })
      .value
  ).toBe("");
});

it("opens a dashboard app and derives its tab from the URL without reloading its guard", async () => {
  replies.set("/api/v1/apps/app-1/", dashboardApp);
  replies.set("/api/v1/apps/app-1/runs/", { items: [] });
  const { router } = await renderRoute(
    "/dashboard/app/app-1?tab=results",
    undefined,
    ({ queryClient }) => {
      queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    }
  );
  await screen.findByRole("heading", { name: dashboardApp.name, level: 1 });
  expect(screen.getByRole("tab", { name: messages.results }).getAttribute("aria-selected")).toBe(
    "true"
  );
  expect(document.title).toBe("Avtalsanalys · Eneo");
  await act(() => router.navigate({ href: "/dashboard/app/app-1?tab=run" }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { name: messages.run }).getAttribute("aria-selected")).toBe(
      "true"
    )
  );
  expect(requestedPaths().filter((path) => path === "/api/v1/apps/app-1/")).toHaveLength(1);
});

it("opens a dashboard result with the app title and its back and new-run links", async () => {
  setViewport("desktop");
  replies.set("/api/v1/apps/app-1/", dashboardApp);
  replies.set("/api/v1/app-runs/run-1/", {
    id: "run-1",
    status: "complete",
    input: { text: "Avtalsfråga", files: [] },
    output: "Svar på avtalsfrågan",
    finished_at: "2026-10-30T08:00:00Z",
    user: { id: "user-1", email: "test@example.se" },
    skill_provenance: []
  });
  await renderRoute("/dashboard/app/app-1/results/run-1");
  await screen.findByText("Svar på avtalsfrågan");
  expect(document.title).toBe("Resultat från Avtalsanalys · Eneo");
  expect(screen.getByRole("link", { name: messages.back }).getAttribute("href")).toBe(
    "/dashboard/app/app-1"
  );
  expect(screen.getByRole("link", { name: messages.new_run }).getAttribute("href")).toBe(
    "/dashboard/app/app-1"
  );
});

it.each(["/dashboard/app/missing", "/dashboard/app/app-1/results/missing"])(
  "maps a missing dashboard resource to not-found: %s",
  async (path) => {
    replies.set("/api/v1/apps/app-1/", dashboardApp);
    replies.set("/api/v1/apps/missing/runs/", { items: [] });
    for (const apiPath of ["/api/v1/apps/missing/", "/api/v1/app-runs/missing/"]) {
      replies.set(
        apiPath,
        new Response("Missing", { status: 404, headers: { [GENERATION]: "document-session" } })
      );
    }
    const { router } = await renderRoute(path);
    await screen.findByRole("heading", { name: messages.page_not_found });
    expect(router.state.matches.some((match) => match.status === "notFound")).toBe(true);
  }
);

it("redirects disabled what's new through the existing root landing route", async () => {
  const { router } = await renderRoute("/whats-new");
  await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
  expect(screen.queryByRole("heading", { name: messages.whats_new })).toBeNull();
});

it("opens enabled what's new using the shared settings and marker owners", async () => {
  replies.set("/api/v1/settings/", { ...context.settings, whats_new_enabled: true });
  replies.set("/api/v1/whats-new/seen/", { seen_version: "0.0.0" });
  await renderRoute("/whats-new");
  await screen.findByRole("heading", { name: messages.whats_new, level: 1 });
  expect(document.title).toBe(`${messages.whats_new} · Eneo`);
  expect(requestedPaths().filter((path) => path === "/api/v1/settings/")).toHaveLength(1);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function createRouteRouter(path = "/does-not-exist") {
  window.history.replaceState({}, "", path);
  const { getQueryClient } = await import("@/lib/api/query");
  const queryClient = getQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const { setRuntimeConfig } = await import("@/lib/runtime-config");
  setRuntimeConfig({
    version: "1.2.3",
    revision: "test",
    help_center_url: null,
    legacy_app_url: null,
    accessibility_statement_url: null,
    request_integration_form_url: null,
    mcp_app_content_origin: null,
    federation_enabled: false
  });
  const owner = await import("@/lib/api/refusal");
  await owner.initializeBrowserSession();
  const { createAppRouter } = await import("@/router");
  const { BootContext } = await import("@/boot-context");
  const router = createAppRouter(
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
    { history: createMemoryHistory({ initialEntries: [path] }) }
  );
  return { router, queryClient, owner, BootContext };
}

async function renderRoute(
  path = "/does-not-exist",
  onRender: ProfilerOnRenderCallback = () => {},
  prepare?: (state: Awaited<ReturnType<typeof createRouteRouter>>) => void
) {
  const state = await createRouteRouter(path);
  prepare?.(state);
  const { router, BootContext } = state;
  render(
    <BootContext value={{ locale: "sv", messages, nonce: undefined }}>
      <Profiler id="app" onRender={onRender}>
        <RouterProvider router={router} />
      </Profiler>
    </BootContext>
  );
  await act(() => router.load());
  return state;
}

it("renders an authenticated unknown path inside the shared shell", async () => {
  await renderRoute();
  const heading = await screen.findByRole("heading", { name: messages.page_not_found });
  expect(heading.closest("main")?.id).toBe("main-content");
  expect(navigate).not.toHaveBeenCalled();
});

it("opens the Skill reference editor in the personal space", async () => {
  await renderRoute("/spaces/personal/skills/new");
  await screen.findByRole("textbox", { name: messages.skills_instructions_label });
  expect(screen.getByRole("button", { name: messages.skills_reference_insert })).toBeTruthy();
  await waitFor(() =>
    expect(document.title).toBe(
      `${messages.skills_library_new_heading} · ${messages.personal} · Eneo`
    )
  );
});

it.each([
  { permissions: ["read"] as const, destination: "/spaces/personal/skills" },
  { permissions: [] as const, destination: "/spaces/personal/overview" }
])(
  "keeps Skill creation behind the space permission: $destination",
  async ({ permissions, destination }) => {
    replies.set(
      "/api/v1/spaces/type/personal/",
      makeSpace({ skillPermissions: [...permissions], overrides: { personal: true } })
    );
    replies.set("/api/v1/spaces/space-1/skills/", { items: [], next_cursor: null });
    const { router } = await renderRoute("/spaces/personal/skills/new");
    await waitFor(() => expect(router.state.location.pathname).toBe(destination));
    expect(screen.queryByRole("textbox", { name: messages.skills_instructions_label })).toBeNull();
  }
);

it.each(["", "/skill-1", "/new"])(
  "denies organization Skills%s before reading them for a non-admin",
  async (suffix) => {
    const { router } = await renderRoute(`/spaces/organization/skills${suffix}`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
    expect(requestedPaths()).not.toContain("/api/v1/spaces/type/organization/");
    expect(requestedPaths().some((path) => path.startsWith("/api/v1/skills/organization/"))).toBe(
      false
    );
    expect(screen.queryByRole("textbox", { name: messages.skills_instructions_label })).toBeNull();
  }
);

it("opens the organization Skill list, saved editor and creation form for an administrator", async () => {
  setViewport("desktop");
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set(
    "/api/v1/spaces/type/organization/",
    makeSpace({ overrides: { organization: true } })
  );
  const revision: Schema<"SkillRevisionPublic"> = {
    id: "revision-1",
    skill_id: "skill-1",
    revision_number: 1,
    display_name: "Report guide",
    description: "Find the report",
    instructions: "Search carefully",
    content_digest: "fixture",
    created_by_user_id: "user-1",
    created_at: "2026-09-01T12:00:00Z"
  };
  const skill: Schema<"OrganizationSkillPublic"> = {
    id: revision.skill_id,
    space_id: "space-1",
    slug: "report-guide",
    is_active: true,
    current_revision_id: revision.id,
    current_revision_number: 1,
    current_revision: revision,
    display_name: revision.display_name,
    description: revision.description,
    content_digest: revision.content_digest,
    created_by_user_id: revision.created_by_user_id,
    created_at: revision.created_at,
    updated_at: revision.created_at,
    publication_state: "draft",
    published_revision_number: null,
    first_published_at: null,
    execution_blocked: false,
    removed_at: null,
    usage: {
      assistant_count: 0,
      app_count: 0,
      distinct_space_count: 0,
      personal_chat_pinned: false
    }
  };
  replies.set("/api/v1/skills/organization/", { items: [skill], next_cursor: null });
  replies.set("/api/v1/skills/organization/skill-1/", skill);
  replies.set("/api/v1/skills/organization/skill-1/revisions/", {
    items: [revision],
    next_cursor: null
  });
  replies.set("/api/v1/skills/organization/skill-1/adoption/", {
    items: [],
    next_cursor: null,
    summary: null
  });
  const { router } = await renderRoute("/spaces/organization/skills");
  const link = await screen.findByRole("link", { name: revision.display_name });
  expect(link.getAttribute("href")).toBe("/spaces/organization/skills/skill-1");
  await waitFor(() =>
    expect(document.title).toBe(`${messages.skills} · ${messages.organization} · Eneo`)
  );
  await act(() => router.navigate({ href: "/spaces/organization/skills/skill-1" }));
  expect(
    ((await screen.findByRole("textbox", { name: messages.name })) as HTMLInputElement).value
  ).toBe(revision.display_name);
  expect(
    screen.getByRole("textbox", { name: messages.skills_instructions_label }).textContent
  ).toBe(revision.instructions);
  expect(screen.getByRole("button", { name: messages.save_changes })).toBeTruthy();
  expect(document.title).toBe(`${messages.skills} · ${messages.organization} · Eneo`);
  await act(() => router.navigate({ href: "/spaces/organization/skills/new" }));
  await screen.findByRole("button", { name: messages.skills_create_action });
  expect((screen.getByRole("textbox", { name: messages.name }) as HTMLInputElement).value).toBe("");
  await waitFor(() =>
    expect(document.title).toBe(
      `${messages.skills_library_new_heading} · ${messages.organization} · Eneo`
    )
  );
  expect(requestedPaths()).not.toContain("/api/v1/spaces/space-1/skills/");
});

it("renders the spaces list with its document title and keeps list distinct from a space ID", async () => {
  await renderRoute("/spaces/list");
  await screen.findByRole("heading", { name: messages.spaces, level: 1 });
  await waitFor(() => expect(document.title).toBe(`${messages.spaces} · Eneo`));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/list/");
});

it("keeps a cached spaces list visible when its background refresh fails", async () => {
  replies.set(
    "/api/v1/spaces/",
    new Response("Unavailable", { status: 503, headers: { [GENERATION]: "document-session" } })
  );
  const { queryClient } = await renderRoute("/spaces/list", undefined, ({ queryClient }) => {
    queryClient.setQueryData(["spaces"], []);
  });
  await screen.findByRole("heading", { name: messages.spaces, level: 1 });
  await waitFor(() => expect(queryClient.getQueryState(["spaces"])?.status).toBe("error"));
  expect(screen.getByRole("heading", { name: messages.spaces, level: 1 })).toBeTruthy();
});

function requestedPaths() {
  return fetcher.mock.calls.map(
    ([input]) =>
      new URL(input instanceof Request ? input.url : String(input), window.location.href).pathname
  );
}

it("renders the existing account profile and local password form in the Vite shell", async () => {
  setViewport("desktop");
  replies.set("/api/v1/users/me/", {
    ...context.user,
    password_change: {
      source: "eneo",
      policy: {
        min_length: 12,
        max_bytes: 72,
        requires_uppercase: false,
        requires_lowercase: false,
        requires_number: false,
        requires_symbol: false
      }
    }
  });
  await renderRoute("/account");
  await screen.findByRole("heading", { name: messages.my_account, level: 1 });
  expect(screen.getByLabelText(messages.current_password, { selector: "input" })).toBeTruthy();
  expect(screen.getByLabelText(messages.new_password, { selector: "input" })).toBeTruthy();
  expect(screen.getByRole("button", { name: messages.save })).toBeTruthy();
  await waitFor(() => expect(document.title).toBe(`${messages.my_account} · Eneo`));
});

it.each([false, true])(
  "shows not-found for a missing space, including an invalidated cached copy (%s)",
  async (cached) => {
    replies.set(
      "/api/v1/spaces/missing/",
      new Response(JSON.stringify({ message: "Not found" }), {
        status: 404,
        headers: { [GENERATION]: "document-session", "content-type": "application/json" }
      })
    );
    const { router } = await renderRoute("/spaces/missing", undefined, ({ queryClient }) => {
      if (cached) {
        queryClient.setQueryData(["spaces", "missing"], makeSpace());
        void queryClient.invalidateQueries({ queryKey: ["spaces", "missing"] });
      }
    });
    await screen.findByRole("heading", { name: messages.page_not_found });
    expect(router.state.location.pathname).toBe("/spaces/missing/overview");
    expect(
      router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.status
    ).toBe("notFound");
    expect(screen.queryAllByText("Upphandling")).toHaveLength(0);
    expect(requestedPaths().filter((path) => path === "/api/v1/spaces/missing/")).toHaveLength(1);
    expect(navigate).not.toHaveBeenCalled();
  }
);

it("uses a fresh space already in the query cache and sets the layout title", async () => {
  const { router } = await renderRoute("/spaces/space-1", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    queryClient.setQueryData(["spaces", "space-1"], makeSpace());
  });
  const layout = router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId");
  expect(layout?.meta).toContainEqual({ title: "Upphandling · Eneo" });
  await waitFor(() => expect(document.title).toBe("Upphandling · Eneo"));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/space-1/");
});

it("redirects a non-admin organization child route before requesting the organization space", async () => {
  const { router } = await renderRoute("/spaces/organization/knowledge");
  await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
  expect(requestedPaths()).not.toContain("/api/v1/spaces/type/organization/");
});

it("lets an administrator load the organization space", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set(
    "/api/v1/spaces/type/organization/",
    makeSpace({ overrides: { organization: true } })
  );
  const { router } = await renderRoute("/spaces/organization");
  const layout = router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId");
  expect(layout?.loaderData).toMatchObject({ organization: true });
  expect(layout?.meta).toContainEqual({ title: `${messages.organization} · Eneo` });
  expect(
    requestedPaths().filter((path) => path === "/api/v1/spaces/type/organization/")
  ).toHaveLength(1);
});

it("uses the stored collapsed preference on the first shell commit", async () => {
  document.cookie = "eneo_sidenav_collapsed=1; Path=/";
  const commits: string[] = [];
  await renderRoute(undefined, () => {
    const toggle = document.querySelector(
      'button[aria-label="Fäll ihop sidomenyn"], button[aria-label="Fäll ut sidomenyn"]'
    );
    if (toggle) commits.push(toggle.getAttribute("aria-expanded")!);
  });
  await screen.findByRole("button", { name: "Fäll ut sidomenyn" });
  expect(commits[0]).toBe("false");
});

it("redirects the root to the signed-in landing path", async () => {
  const { router } = await renderRoute("/");
  await screen.findByRole("button", { name: "Chat new: 0" });
  expect(router.state.location.pathname).toBe("/spaces/personal/chat");
  expect(document.getElementById("main-content")).not.toBeNull();
});

it("redirects the spaces index to its list without treating it as a space ID", async () => {
  const { router } = await renderRoute("/spaces");
  await screen.findByRole("heading", { name: messages.spaces, level: 1 });
  expect(router.state.location.pathname).toBe("/spaces/list");
  expect(requestedPaths()).not.toContain("/api/v1/spaces/list/");
});

it.each([
  ["personal", "/spaces/personal/chat", `${messages.personal} · Eneo`],
  ["space-1", "/spaces/space-1/overview", "Upphandling · Eneo"]
])(
  "redirects the %s space index and inherits its space title",
  async (spaceId, destination, title) => {
    replies.set("/api/v1/spaces/space-1/", makeSpace());
    const { router } = await renderRoute(`/spaces/${spaceId}`);
    await waitFor(() => expect(router.state.location.pathname).toBe(destination));
    await waitFor(() => expect(document.title).toBe(title));
    expect(screen.queryByRole("heading", { name: messages.page_not_found })).toBeNull();
  }
);

it("keeps the space frame mounted when switching from overview to members", async () => {
  setViewport("desktop");
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  const { router } = await renderRoute("/spaces/space-1/overview");
  const heading = await screen.findByRole("heading", { name: "Upphandling", level: 1 });
  await act(() => router.navigate({ href: "/spaces/space-1/members" }));
  await screen.findByRole("heading", { name: messages.members });
  await waitFor(() => expect(document.title).toBe(`${messages.members} · Upphandling · Eneo`));
  expect(screen.getByRole("heading", { name: "Upphandling", level: 1 })).toBe(heading);
});

it("preserves chat state when its saved session updates the URL without another space read", async () => {
  const { router } = await renderRoute("/spaces/personal/chat", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  });
  const chat = await screen.findByRole("button", { name: "Chat new: 0" });
  const initialReads = requestedPaths().filter(
    (path) => path === "/api/v1/spaces/type/personal/"
  ).length;
  fireEvent.click(chat);
  await waitFor(() =>
    expect(router.state.location.search).toMatchObject({ session_id: "saved-session" })
  );
  expect(await screen.findByRole("button", { name: "Chat saved-session: 1" })).toBe(chat);
  expect(requestedPaths().filter((path) => path === "/api/v1/spaces/type/personal/")).toHaveLength(
    initialReads
  );
});

it("flushes a settings draft to its original space and opens the next space with its own values", async () => {
  const first = makeSpace();
  const second = makeSpace({ overrides: { id: "space-2", name: "Personalfrågor" } });
  replies.set("/api/v1/spaces/space-1/", first);
  replies.set("/api/v1/spaces/space-2/", second);
  replies.set("/api/v1/security-classifications/", {
    security_enabled: false,
    security_classifications: []
  });
  replies.set("/api/v1/ai-models/", {
    completion_models: [],
    embedding_models: [],
    transcription_models: []
  });
  replies.set("/api/v1/mcp-servers/settings/", { items: [] });
  replies.set("/api/v1/api-keys/notification-subscriptions", { items: [] });
  replies.set("/api/v1/api-keys", { items: [], total_count: 0, next_cursor: null });
  const read = fetcher.getMockImplementation()!;
  const writes: { path: string; body: unknown }[] = [];
  fetcher.mockImplementation(async (input, init) => {
    if ((input instanceof Request ? input.method : init?.method) !== "PATCH")
      return read(input, init);
    const request = new Request(input, init);
    const path = new URL(request.url).pathname;
    const body: unknown = await request.json();
    writes.push({ path, body });
    return new Response(JSON.stringify({ ...first, name: "Uppdaterat namn" }), {
      headers: { "content-type": "application/json", [GENERATION]: "document-session" }
    });
  });
  const { router } = await renderRoute("/spaces/space-1/settings");
  const name = await screen.findByLabelText<HTMLInputElement>(messages.name, { selector: "input" });
  fireEvent.change(name, { target: { value: "Uppdaterat namn" } });
  await act(() => router.navigate({ href: "/spaces/space-1/settings?section=models" }));
  expect(screen.getByLabelText(messages.name, { selector: "input" })).toBe(name);
  expect(name.value).toBe("Uppdaterat namn");
  expect(writes).toHaveLength(0);
  await act(() => router.navigate({ href: "/spaces/space-2/settings" }));
  await waitFor(() =>
    expect(
      screen.getByLabelText<HTMLInputElement>(messages.name, { selector: "input" }).value
    ).toBe(second.name)
  );
  await waitFor(() =>
    expect(writes).toEqual([{ path: "/api/v1/spaces/space-1/", body: { name: "Uppdaterat namn" } }])
  );
  expect(screen.getByLabelText(messages.name, { selector: "input" })).not.toBe(name);
});

it("preloads the session using only GET requests", async () => {
  const { router } = await createRouteRouter();
  fetcher.mockClear();
  await router.preloadRoute({ to: "/$", params: { _splat: "another" } });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(6));
  for (const [input, init] of fetcher.mock.calls) {
    expect(input instanceof Request ? input.method : (init?.method ?? "GET")).toBe("GET");
  }
  expect(navigate).not.toHaveBeenCalled();
});

it("waits for a fresh existence check before re-entering a cached space route", async () => {
  replies.set("/api/v1/spaces/space-1/", makeSpace());
  const { router, queryClient } = await renderRoute(
    "/spaces/space-1",
    undefined,
    ({ queryClient }) => {
      queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    }
  );
  expect(
    router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.status
  ).toBe("success");
  await act(() => router.navigate({ to: "/account" }));
  await screen.findByRole("heading", { name: messages.my_account, level: 1 });
  await queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"], refetchType: "none" });
  let release!: (response: Response) => void;
  replies.set(
    "/api/v1/spaces/space-1/",
    new Promise<Response>((resolve) => {
      release = resolve;
    })
  );
  const previousReads = requestedPaths().filter(
    (path) => path === "/api/v1/spaces/space-1/"
  ).length;
  let navigation!: Promise<void>;
  await act(async () => {
    navigation = router.navigate({ to: "/spaces/$spaceId", params: { spaceId: "space-1" } });
  });
  try {
    await waitFor(() =>
      expect(requestedPaths().filter((path) => path === "/api/v1/spaces/space-1/")).toHaveLength(
        previousReads + 1
      )
    );
    expect(router.state.status).toBe("pending");
    expect(screen.queryAllByText("Upphandling")).toHaveLength(0);
  } finally {
    await act(async () => {
      release(
        new Response(JSON.stringify({ message: "Not found" }), {
          status: 404,
          headers: { [GENERATION]: "document-session", "content-type": "application/json" }
        })
      );
      await navigation;
    });
  }
  expect(
    router.state.matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.status
  ).toBe("notFound");
  expect(screen.queryAllByText("Upphandling")).toHaveLength(0);
  expect(screen.getByRole("heading", { name: messages.page_not_found })).toBeTruthy();
});

it("starts the other five session resources together without blocking the route gate", async () => {
  const paths = [...replies.keys()].filter(
    (path) => path !== "/api/v1/users/me/" && !path.startsWith("/api/v1/spaces/")
  );
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  for (const path of paths) {
    const reply = replies.get(path);
    replies.set(
      path,
      pending.then(() => reply)
    );
  }
  await renderRoute();
  const requested = fetcher.mock.calls.map(
    ([input]) =>
      new URL(input instanceof Request ? input.url : String(input), window.location.href).pathname
  );
  expect(requested).toEqual(expect.arrayContaining(paths));
  expect(document.getElementById("main-content")).toBeNull();
  await act(async () => release());
  await screen.findByRole("heading", { name: messages.page_not_found });
});

it("leaves a me 401 to the single refusal owner and never renders the shell", async () => {
  replies.set(
    "/api/v1/users/me/",
    new Response(JSON.stringify({ message: "Unauthorized" }), {
      status: 401,
      headers: { [GENERATION]: "document-session", "content-type": "application/json" }
    })
  );
  await renderRoute();
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fdoes-not-exist")
  );
  expect(document.getElementById("main-content")).toBeNull();
});

it("keeps page state mounted through marker changes and a failed session refresh", async () => {
  function StatefulPage() {
    const [count, setCount] = useState(0);
    return <button onClick={() => setCount(count + 1)}>Edited {count}</button>;
  }
  const { Route } = await import("./_app/$");
  Route.update({ component: StatefulPage });
  const { queryClient } = await renderRoute();
  const button = await screen.findByRole("button", { name: "Edited 0" });
  fireEvent.click(button);
  const main = button.closest("main");
  const { sessionKeys } = await import("@/lib/api/session");
  await act(async () => {
    queryClient.setQueryData(sessionKeys.whatsNew, { seen_version: "1", announced_version: "2" });
  });
  replies.set("/api/v1/users/tenant/", new Response("Unavailable", { status: 500 }));
  await act(() => queryClient.invalidateQueries({ queryKey: sessionKeys.tenant }));
  expect(queryClient.getQueryState(sessionKeys.tenant)?.status).toBe("error");
  expect(screen.getByRole("button", { name: "Edited 1" })).toBe(button);
  expect(button.closest("main")).toBe(main);
  expect(navigate).not.toHaveBeenCalled();
});

it("holds a cache-only navigation for the resume check and blocks a changed session", async () => {
  const { router, queryClient, owner } = await renderRoute();
  await screen.findByRole("heading", { name: messages.page_not_found });
  const { sessionKeys } = await import("@/lib/api/session");
  expect(queryClient.getQueryData(sessionKeys.me)).toBeDefined();
  let release!: (response: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      })
  );
  const check = owner.checkBrowserSession().catch((error: unknown) => error);
  let finished = false;
  let navigation!: Promise<void>;
  await act(async () => {
    navigation = router.navigate({ to: "/$", params: { _splat: "another" } });
    void navigation.then(() => {
      finished = true;
    });
  });
  expect(router.state.status).toBe("pending");
  expect(finished).toBe(false);
  await act(async () => {
    release(new Response(null, { status: 204, headers: { [GENERATION]: "another-session" } }));
    await check;
    await navigation;
  });
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fdoes-not-exist");
  expect(queryClient.getQueryData(sessionKeys.me)).toBeUndefined();
  expect(document.getElementById("main-content")).toBeNull();
});

it.each([
  ["appearance", "account_appearance_language", "/account"],
  ["copy-format", "account_copy_format", "/account"],
  ["password", "change_password", "/account"],
  ["api-keys", "my_api_keys", "/account/api-keys"],
  ["integrations", "my_integrations", "/account/integrations"]
] as const)(
  "renders account/%s with its title and one current account link",
  async (page, titleKey, currentHref) => {
    setViewport("desktop");
    replies.set("/api/v1/users/me/", {
      ...context.user,
      password_change: {
        source: "eneo",
        policy: {
          min_length: 12,
          max_bytes: 72,
          requires_uppercase: false,
          requires_lowercase: false,
          requires_number: false,
          requires_symbol: false
        }
      }
    });
    replies.set("/api/v1/integrations/me/", { items: [] });
    replies.set("/api/v1/api-keys", { items: [], total_count: 0, next_cursor: null });
    replies.set("/api/v1/api-keys/notification-preferences", {
      enabled: false,
      days_before_expiry: [7],
      auto_follow_published_assistants: false
    });
    replies.set("/api/v1/api-keys/policy-constraints", {
      notification_policy: {
        enabled: true,
        default_days_before_expiry: [7],
        max_days_before_expiry: null,
        allow_auto_follow_published_assistants: true,
        allow_auto_follow_published_apps: true
      }
    });
    await renderRoute(`/account/${page}`);
    await waitFor(() => expect(document.title).toBe(`${messages[titleKey]} · Eneo`));
    const navigation = screen.getByRole("navigation", { name: messages.shell_account_nav_label });
    const current = navigation.querySelectorAll('a[aria-current="true"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe(currentHref);
    switch (page) {
      case "appearance":
        await screen.findByRole("radiogroup", { name: messages.theme });
        break;
      case "copy-format":
        await screen.findByRole("radio", { name: messages.copy_format_markdown });
        break;
      case "password":
        await screen.findByLabelText(messages.current_password, { selector: "input" });
        expect(screen.getByRole("button", { name: messages.save })).toBeTruthy();
        break;
      case "api-keys":
        await screen.findByRole("heading", { name: messages.api_keys_no_keys });
        break;
      case "integrations":
        await screen.findByText(messages.no_integrations_enabled);
        break;
    }
  }
);

it("returns a signed-out account visit to login with its destination preserved", async () => {
  replies.set(
    "/api/v1/users/me/",
    new Response(JSON.stringify({ message: "Unauthorized" }), {
      status: 401,
      headers: { [GENERATION]: "document-session", "content-type": "application/json" }
    })
  );
  await renderRoute("/account");
  await waitFor(() => expect(navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Faccount"));
  expect(document.getElementById("main-content")).toBeNull();
});

it.each(["/admin/users", "/admin/user-groups", "/admin/usage/users/missing", "/admin/roles"])(
  "denies an admin page before reading its data: %s",
  async (path) => {
    const { router } = await renderRoute(path);
    expect(router.state.location.pathname).toBe("/spaces/personal/chat");
    expect(
      requestedPaths().some((entry) =>
        /\/admin\/|\/token-usage\/|\/roles\/|\/user-groups\//.test(entry)
      )
    ).toBe(false);
  }
);

it("opens admin user groups with its title and one current admin link", async () => {
  setViewport("desktop");
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set("/api/v1/user-groups/", {
    items: [{ id: "group-1", name: "Kommunikation", users: [] }],
    count: 1
  });
  await renderRoute("/admin/user-groups", undefined, ({ queryClient }) => {
    queryClient.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  });
  const table = await screen.findByRole("table", { name: messages.user_groups });
  expect(table.textContent).toContain("Kommunikation");
  expect(document.title).toBe(`${messages.user_groups} · Eneo`);
  const link = screen.getByRole("link", { name: messages.user_groups });
  expect(link.getAttribute("href")).toBe("/admin/user-groups");
  expect(link.getAttribute("aria-current")).toBe("page");
  const navigation = screen.getByRole("navigation", { name: "Administration" });
  expect(navigation.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  expect(requestedPaths().filter((path) => path === "/api/v1/user-groups/")).toHaveLength(1);
});

it("opens the admin users table with the feature's URL filters and one session read", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set("/api/v1/admin/users/", {
    items: [
      {
        ...context.user,
        id: "listed-user",
        username: "Anna Lind",
        email: "anna@example.test",
        state: "active",
        roles: [],
        user_groups: []
      }
    ],
    metadata: {
      page: 2,
      page_size: 100,
      total_pages: 2,
      total_count: 101,
      counts: { active: 101, inactive: 0 },
      has_next: false,
      has_previous: true
    }
  });
  replies.set("/api/v1/roles/", { roles: { items: [] }, predefined_roles: { items: [] } });
  replies.set("/api/v1/admin/password-policy", { max_age_days: null });
  await renderRoute("/admin/users?page=2&search=anna&role_id=role-1");
  const table = await screen.findByRole("table", { name: messages.active_users });
  expect(table.textContent).toContain("anna@example.test");
  const requests = fetcher.mock.calls.map(
    ([input]) => new URL(input instanceof Request ? input.url : String(input), window.location.href)
  );
  const users = requests.find((url) => url.pathname === "/api/v1/admin/users/");
  expect(users?.searchParams.get("page")).toBe("2");
  expect(users?.searchParams.get("search_email")).toBe("anna");
  expect(users?.searchParams.get("role_id")).toBe("role-1");
  expect(requestedPaths().filter((path) => path === "/api/v1/users/me/")).toHaveLength(1);
  expect(document.title).toBe(`${messages.users} · Eneo`);
});

it("warms admin usage independently when a storage-spaces request fails", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  const totals = {
    total_token_usage: 1500,
    total_input_token_usage: 1200,
    total_output_token_usage: 300,
    models: []
  };
  const storage = { total_used: 600, personal_used: 200, shared_used: 400, limit: 1000 };
  replies.set("/api/v1/token-usage/", totals);
  replies.set("/api/v1/storage/", storage);
  replies.set("/api/v1/storage/spaces/", new Response("Unavailable", { status: 500 }));
  const { router, queryClient } = await createRouteRouter("/admin/usage");
  await router.load();
  const { browserApi } = await import("@/lib/api/browser");
  const { tokenUsageQueryOptions, storageQueryOptions, storageSpacesQueryOptions } =
    await import("@/features/admin/usage/usage");
  await waitFor(() =>
    expect(queryClient.getQueryData(tokenUsageQueryOptions(browserApi).queryKey)).toEqual(totals)
  );
  expect(queryClient.getQueryData(storageQueryOptions(browserApi).queryKey)).toEqual(storage);
  await waitFor(() =>
    expect(queryClient.getQueryState(storageSpacesQueryOptions(browserApi).queryKey)?.status).toBe(
      "error"
    )
  );
  expect(router.state.matches.every((match) => match.status === "success")).toBe(true);
});

it.each([404, 500])("keeps a user usage %s in the correct route boundary", async (status) => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set("/api/v1/token-usage/users/missing/summary", new Response("Unavailable", { status }));
  replies.set("/api/v1/token-usage/users/missing", {
    total_token_usage: 0,
    total_input_token_usage: 0,
    total_output_token_usage: 0,
    models: []
  });
  await renderRoute("/admin/usage/users/missing?from=2026-09-01&to=2026-09-30");
  await screen.findByRole("heading", {
    name: status === 404 ? messages.page_not_found : messages.something_went_wrong
  });
});

it("only reads data while preloading admin users and usage", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set("/api/v1/admin/users/", { items: [] });
  replies.set("/api/v1/roles/", { roles: { items: [] }, predefined_roles: { items: [] } });
  replies.set("/api/v1/admin/password-policy", { max_age_days: null });
  replies.set("/api/v1/token-usage/", { models: [] });
  replies.set("/api/v1/storage/", {});
  replies.set("/api/v1/storage/spaces/", { items: [] });
  const { router } = await createRouteRouter();
  await router.load();
  await router.preloadRoute({ to: "/admin/users" });
  await router.preloadRoute({ to: "/admin/usage" });
  await waitFor(() => expect(requestedPaths()).toContain("/api/v1/storage/spaces/"));
  expect(
    fetcher.mock.calls.every(
      ([input, init]) =>
        (input instanceof Request ? input.method : (init?.method ?? "GET")) === "GET"
    )
  ).toBe(true);
});

it("opens enabled federation administration with its navigation and title", async () => {
  setViewport("desktop");
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set("/api/v1/admin/federation", {});
  const { runtimeConfig, setRuntimeConfig } = await import("@/lib/runtime-config");
  await renderRoute("/admin/federation", undefined, () => {
    setRuntimeConfig({ ...runtimeConfig(), federation_enabled: true });
  });
  await screen.findByRole("heading", { level: 1, name: messages.federation_admin_title });
  expect(document.title).toBe(`${messages.federation_admin_title} · Eneo`);
  expect(
    screen.getByRole("link", { name: messages.federation_admin_nav }).getAttribute("href")
  ).toBe("/admin/federation");
  expect(requestedPaths()).toContain("/api/v1/admin/federation");
});

it("hides disabled federation administration and rejects its URL before the API read", async () => {
  setViewport("desktop");
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  const { router } = await renderRoute("/admin/federation");
  await screen.findByRole("heading", { name: messages.page_not_found });
  expect(router.state.matches.some((match) => match.status === "notFound")).toBe(true);
  expect(screen.queryByRole("link", { name: messages.federation_admin_nav })).toBeNull();
  expect(requestedPaths()).not.toContain("/api/v1/admin/federation");
});

it("keeps federation administration behind the existing admin guard", async () => {
  const { runtimeConfig, setRuntimeConfig } = await import("@/lib/runtime-config");
  const { router } = await renderRoute("/admin/federation", undefined, () => {
    setRuntimeConfig({ ...runtimeConfig(), federation_enabled: true });
  });
  await waitFor(() => expect(router.state.location.pathname).toBe("/spaces/personal/chat"));
  expect(requestedPaths()).not.toContain("/api/v1/admin/federation");
});

it("preloads federation with GET requests without waiting for its optional data", async () => {
  replies.set("/api/v1/users/me/", testAppContext({ permissions: ["admin"] }).user);
  replies.set("/api/v1/admin/federation", new Promise(() => {}));
  const { router } = await createRouteRouter();
  const { runtimeConfig, setRuntimeConfig } = await import("@/lib/runtime-config");
  setRuntimeConfig({ ...runtimeConfig(), federation_enabled: true });
  fetcher.mockClear();
  await router.preloadRoute({ to: "/admin/federation" });
  await waitFor(() => expect(requestedPaths()).toContain("/api/v1/admin/federation"));
  for (const [input, init] of fetcher.mock.calls) {
    expect(input instanceof Request ? input.method : (init?.method ?? "GET")).toBe("GET");
  }
});
