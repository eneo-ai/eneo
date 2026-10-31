/**
 * Test-only: renders UI inside the app's providers, in Swedish (the default
 * locale), so tests query what users see and hear: use-intl with the real
 * catalog, the Astryx provider (its Swedish strings, the app's link), React Query,
 * the Radix tooltip provider, the signed-in app context and the app shell's
 * context. Not imported by app code.
 */
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { render, renderHook } from "@testing-library/react";
import { AppIntlProvider } from "@/components/providers/intl-provider";
import { AppContextProvider, type AppContextData } from "@/components/providers/app-context";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import { ShellContext, type ShellContextValue } from "@/components/shell/shell-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import { makeQueryClient } from "@/lib/api/query";
import type { Permission } from "@/lib/auth/permissions";
import messages from "@/lib/i18n/messages/sv.json";
import * as appNavigation from "@/lib/navigation";
import * as navigation from "./navigation";

/**
 * The app's query client (`makeQueryClient`: data stays fresh for 30 s, so
 * stale and invalidated data refetch as in the app) without retries, so a
 * failed request fails the first time.
 */
export function testQueryClient(): QueryClient {
  const client = makeQueryClient();
  const defaults = client.getDefaultOptions();
  client.setDefaultOptions({
    ...defaults,
    queries: { ...defaults.queries, retry: false },
    mutations: { ...defaults.mutations, retry: false }
  });
  return client;
}

type AppContextOverrides = { [Key in keyof AppContextData]?: Partial<AppContextData[Key]> } & {
  /** The user's tenant permissions (held by one role). */
  permissions?: Permission[];
};

/**
 * The signed-in app context: Anna Lind at Sundsvalls kommun without
 * permissions. Each field merges its overrides into the default.
 *
 * @example testAppContext({ permissions: ["admin"], settings: { using_templates: true } })
 */
export function testAppContext({
  permissions = [],
  ...overrides
}: AppContextOverrides = {}): AppContextData {
  const defaults = {
    user: {
      id: "user-1",
      email: "anna.lind@example.se",
      username: "Anna Lind",
      predefined_roles: [],
      roles: [{ id: "role-1", name: "Medarbetare", permissions }],
      user_groups: []
    },
    tenant: {
      id: "tenant-1",
      name: "sundsvall",
      display_name: "Sundsvalls kommun",
      show_model_pricing: false
    },
    settings: { using_templates: false, api_key_expiry_notifications: false, chatbot_widget: null },
    federationStatus: { has_multi_tenant_federation: false },
    featureFlags: { federation: false },
    limits: { attachments: { formats: [] }, info_blobs: { formats: [] } },
    links: { accessibilityStatement: null, helpCenter: null, legacyApp: null },
    versions: { frontend: "0.1.0", backend: "1.2.3" }
  };
  return Object.fromEntries(
    Object.entries(defaults).map(([key, value]) => [
      key,
      { ...value, ...overrides[key as keyof AppContextData] }
    ])
  ) as unknown as AppContextData;
}

/** A shell context whose actions do nothing (pass `vi.fn()`s to check them). */
export const noopShell: ShellContextValue = {
  openPalette: () => {},
  openCreateSpace: () => {}
};

export type RenderInAppOptions = {
  /** Default: a fresh `testQueryClient()`. Seed it with `setQueryData` first. */
  queryClient?: QueryClient;
  /** Default: `testAppContext()`. */
  appContext?: AppContextData;
  /** Default: `noopShell`. */
  shell?: ShellContextValue;
  /**
   * The route the navigation hooks report, e.g. `/admin/users?page=2`.
   * Needs `vi.mock("@/lib/navigation", () => import("@/test/navigation"))`.
   */
  route?: string;
};

function providers({
  queryClient = testQueryClient(),
  appContext = testAppContext(),
  shell = noopShell,
  route
}: RenderInAppOptions) {
  if (route !== undefined) {
    let mocked = false;
    try {
      mocked = appNavigation.useRouter === navigation.useRouter;
    } catch {
      // A test's own navigation mock without useRouter.
    }
    if (!mocked) {
      throw new Error(
        'renderInApp({ route }) needs vi.mock("@/lib/navigation", () => import("@/test/navigation")).'
      );
    }
    navigation.setRoute(route);
  }

  function Providers({ children }: { children: React.ReactNode }) {
    return (
      <AppIntlProvider locale="sv" messages={messages}>
        <AstryxProvider>
          <QueryClientProvider client={queryClient}>
            <TooltipProvider>
              <AppContextProvider value={appContext}>
                <ShellContext value={shell}>{children}</ShellContext>
              </AppContextProvider>
            </TooltipProvider>
          </QueryClientProvider>
        </AstryxProvider>
      </AppIntlProvider>
    );
  }
  return { queryClient, Providers };
}

/**
 * Renders `ui` in the app's providers (see the top of this file). Returns
 * Testing Library's result and the query client; `rerender(ui)` keeps the
 * providers and the client.
 *
 * @example
 * const { container } = renderInApp(<PageHeader title="Ytor" />);
 * renderInApp(<AppShellFrame>{page}</AppShellFrame>, {
 *   route: "/admin/models",
 *   appContext: testAppContext({ permissions: ["admin"] })
 * });
 */
export function renderInApp(ui: React.ReactNode, options: RenderInAppOptions = {}) {
  const { queryClient, Providers } = providers(options);
  return { queryClient, ...render(ui, { wrapper: Providers }) };
}

/** Renders a hook in the app's providers, like `renderInApp`. */
export function renderHookInApp<Result>(hook: () => Result, options: RenderInAppOptions = {}) {
  const { queryClient, Providers } = providers(options);
  return { queryClient, ...renderHook(hook, { wrapper: Providers }) };
}
