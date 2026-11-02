// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShellFrame } from "@/components/shell/app-shell";
import { setRoute } from "@/test/navigation";
import { renderInApp, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { AccountPageBar } from "@/features/account/account-page-bar";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));

afterEach(cleanup);

function renderAccountPage(path: string) {
  setRoute(path);
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces"], []);
  queryClient.setQueryData(["dashboard"], { spaces: { items: [] } });
  return renderInApp(
    <AppShellFrame>
      <AccountPageBar />
    </AppShellFrame>,
    { queryClient }
  );
}

describe("AccountPageBar on a phone", () => {
  it.each([
    ["/account/appearance", "Utseende och språk"],
    ["/account/copy-format", "Kopieringsformat"],
    ["/account/password", "Byt lösenord"],
    ["/account/api-keys", "Mina API-nycklar"],
    ["/account/integrations", "Integrationer"]
  ])("takes %s back to Konto, named %s", (path, title) => {
    setViewport("phone");
    const { container } = renderAccountPage(path);
    const back = screen.getByRole("link", { name: "Tillbaka till Konto" });
    expect(back.getAttribute("href")).toBe("/account");
    expect(back.closest("[data-own-mobile-header]")).toBeTruthy();
    // The page's heading below 1024 px; from there the layout's "Mitt konto".
    const heading = screen.getByRole("heading", { level: 1, name: title });
    expect(heading.className).toContain("lg:hidden");
    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });

  it("leaves Konto itself to the shell's top bar and its menu", () => {
    setViewport("phone");
    const { container } = renderAccountPage("/account");
    expect(screen.queryByRole("link", { name: "Tillbaka till Konto" })).toBeNull();
    expect(container.querySelector("[data-own-mobile-header]")).toBeNull();
  });
});
