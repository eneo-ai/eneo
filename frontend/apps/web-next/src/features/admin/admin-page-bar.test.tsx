// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShellFrame } from "@/components/shell/app-shell";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import { renderInApp, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { AdminPageBar } from "@/features/admin/admin-page-bar";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));

afterEach(cleanup);

function renderAdminPage(path: string) {
  setRoute(path);
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], []);
  queryClient.setQueryData(["dashboard"], { spaces: { items: [] } });
  return renderInApp(
    <AppShellFrame>
      <AdminPageBar />
      <h1>Sidan</h1>
    </AppShellFrame>,
    { queryClient }
  );
}

const back = (name: string) => screen.getByRole("link", { name: `Tillbaka till ${name}` });

describe("AdminPageBar on a phone", () => {
  it("keeps the federation title in the bar", () => {
    setViewport("phone");
    renderAdminPage("/admin/federation");
    expect(screen.getByText("Inloggning (SSO)").closest("[data-own-mobile-header]")).toBeTruthy();
  });

  it("takes an admin area back to Administration, in place of the top bar", async () => {
    setViewport("phone");
    const { container } = renderAdminPage("/admin/users");
    expect(back("Administration").getAttribute("href")).toBe("/admin");
    // Pushed screen: the bar marks itself, and the shell's top bar gives way
    // to it in CSS (tests/shell-headers.spec.ts checks it in a browser).
    expect(back("Administration").closest("[data-own-mobile-header]")).toBeTruthy();
    // The page keeps the one h1; the bar's title is decoration.
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    await expectNoAxeViolations(container);
  });

  it("takes a page below an area back to that area", () => {
    setViewport("phone");
    renderAdminPage("/admin/usage/users/u-1");
    expect(back("Användning").getAttribute("href")).toBe("/admin/usage");
  });

  it("names the Flow settings area in its mobile bar", () => {
    setViewport("phone");
    renderAdminPage("/admin/flow-settings");
    expect(back("Administration").getAttribute("href")).toBe("/admin");
    expect(screen.getByText("Flöden")).toBeTruthy();
  });

  it("takes an MCP server back to Verktyg, where the servers are listed", () => {
    setViewport("phone");
    renderAdminPage("/admin/mcp-servers/server-1");
    expect(back("Verktyg").getAttribute("href")).toBe("/admin/tools?tab=mcp-servers");
  });

  it("leaves the admin overview to the top bar with the menu", () => {
    setViewport("phone");
    const { container } = renderAdminPage("/admin");
    expect(screen.queryByRole("link", { name: "Tillbaka till Administration" })).toBeNull();
    expect(container.querySelector("[data-own-mobile-header]")).toBeNull();
  });
});
