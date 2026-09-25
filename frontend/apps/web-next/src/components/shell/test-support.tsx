/**
 * Test helpers for the shell's component tests (not shipped: nothing in the
 * app imports this module). jsdom lacks the native dialog and popover APIs
 * that Astryx's Dialog, MobileNav, CommandPalette and DropdownMenu use, and
 * matchMedia / ResizeObserver.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { vi } from "vitest";
import { AppContextProvider, type AppContextData } from "@/components/providers/app-context";
import messages from "@/lib/i18n/messages/sv.json";
import type { Permission } from "@/lib/auth/permissions";
import { ShellContext, type ShellContextValue } from "./shell-context";

export function installBrowserMocks({ mobile = false }: { mobile?: boolean } = {}) {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  });
  HTMLElement.prototype.showPopover = vi.fn(function (this: HTMLElement) {
    this.setAttribute("popover-open", "");
    const event = new Event("toggle", { bubbles: false });
    Object.defineProperty(event, "newState", { value: "open" });
    this.dispatchEvent(event);
  });
  HTMLElement.prototype.hidePopover = vi.fn(function (this: HTMLElement) {
    this.removeAttribute("popover-open");
    const event = new Event("toggle", { bubbles: false });
    Object.defineProperty(event, "newState", { value: "closed" });
    this.dispatchEvent(event);
  });
  const originalMatches = HTMLElement.prototype.matches;
  HTMLElement.prototype.matches = function (this: HTMLElement, selector: string) {
    if (selector === ":popover-open") return this.hasAttribute("popover-open");
    return originalMatches.call(this, selector);
  };
  Element.prototype.scrollIntoView = vi.fn();
  // Dialog scroll locks restore the scroll position.
  window.scrollTo = vi.fn() as typeof window.scrollTo;
  // Astryx Dialog looks its title up with CSS.escape, which jsdom lacks.
  if (typeof globalThis.CSS?.escape !== "function") {
    vi.stubGlobal("CSS", {
      ...globalThis.CSS,
      escape: (value: string) => value.replace(/([^\w-])/g, "\\$1")
    });
  }
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: mobile && query.includes("width <"),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false
  }));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
}

export function testQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } }
  });
}

export function appContext({
  permissions = [],
  accessibilityStatement = null,
  usingTemplates = false
}: {
  permissions?: Permission[];
  accessibilityStatement?: string | null;
  usingTemplates?: boolean;
} = {}): AppContextData {
  return {
    user: {
      id: "user-1",
      email: "anna.lind@example.se",
      username: "anna.lind",
      roles: [{ permissions }]
    },
    tenant: { id: "tenant-1", name: "sundsvall", display_name: "Sundsvalls kommun" },
    settings: { using_templates: usingTemplates, api_key_expiry_notifications: false },
    federationStatus: { has_multi_tenant_federation: false },
    limits: {},
    featureFlags: { showWebSearch: false },
    links: { accessibilityStatement },
    versions: { frontend: "0.1.0", backend: "1.2.3" }
  } as unknown as AppContextData;
}

export const noopShell: ShellContextValue = {
  openPalette: () => {},
  openCreateSpace: () => {}
};

export function renderWithProviders(
  ui: React.ReactNode,
  {
    queryClient = testQueryClient(),
    context = appContext(),
    shell = noopShell
  }: {
    queryClient?: QueryClient;
    context?: AppContextData;
    shell?: ShellContextValue;
  } = {}
) {
  // A wrapper (not a wrapped tree) so `rerender(ui)` keeps the providers.
  function Providers({ children }: { children: React.ReactNode }) {
    return (
      <NextIntlClientProvider locale="sv" messages={messages} timeZone="Europe/Stockholm">
        <QueryClientProvider client={queryClient}>
          <AppContextProvider value={context}>
            <ShellContext value={shell}>{children}</ShellContext>
          </AppContextProvider>
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  }
  return { queryClient, ...render(ui, { wrapper: Providers }) };
}
