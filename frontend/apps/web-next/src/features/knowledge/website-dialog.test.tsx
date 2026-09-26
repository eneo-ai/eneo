// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeWebsite } from "@/features/spaces/testing/space-fixture";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const space = makeSpace();
  return { useSpace: () => useSpaceFromQuery(() => space as Space) };
});

import type { Website } from "./knowledge";
import { WebsiteDialog } from "./website-dialog";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

function renderDialog(website?: Website) {
  renderInApp(<WebsiteDialog website={website} open onOpenChange={() => {}} />);
  return screen.getByRole("dialog", {
    name: website ? "Redigera webbplatsintegration" : "Skapa en webbplatsintegration"
  });
}

const field = (dialog: HTMLElement, name: RegExp) =>
  within(dialog).getByLabelText(name) as HTMLInputElement;

afterEach(() => vi.clearAllMocks());

describe("WebsiteDialog", () => {
  it("asks for the site's password twice and says at the confirmation when they differ", async () => {
    api.GET.mockImplementation(() => ok(null));
    api.POST.mockReturnValue(new Promise(() => {}));
    const dialog = renderDialog();
    fireEvent.change(field(dialog, /^URL/), {
      target: { value: "https://intranat.sundsvall.se" }
    });
    fireEvent.click(within(dialog).getByRole("switch", { name: /HTTP Basic Authentication/ }));
    fireEvent.change(field(dialog, /^Användarnamn/), { target: { value: "crawler" } });

    for (const input of [field(dialog, /^Lösenord/), field(dialog, /^Bekräfta lösenord/)]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("new-password");
      expect(input.getAttribute("aria-required")).toBe("true");
    }
    fireEvent.change(field(dialog, /^Lösenord/), { target: { value: "hemlis-1" } });
    field(dialog, /^Bekräfta lösenord/).focus();
    fireEvent.change(field(dialog, /^Bekräfta lösenord/), { target: { value: "hemlis-2" } });
    fireEvent.blur(field(dialog, /^Bekräfta lösenord/));

    const error = within(dialog).getByText("Lösenorden matchar inte");
    const confirmation = field(dialog, /^Bekräfta lösenord/);
    expect(confirmation.getAttribute("aria-invalid")).toBe("true");
    expect(confirmation.getAttribute("aria-describedby")).toContain(error.id);
    const create = within(dialog).getByRole("button", { name: "Skapa webbplats" });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    await expectNoAxeViolations(document.body);

    fireEvent.change(confirmation, { target: { value: "hemlis-1" } });
    expect((create as HTMLButtonElement).disabled).toBe(false);
    fireEvent.submit(create.closest("form")!);

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/spaces/{id}/knowledge/websites/", {
        params: { path: { id: "space-1" } },
        body: expect.objectContaining({
          http_auth_username: "crawler",
          http_auth_password: "hemlis-1"
        })
      })
    );
  });

  it("keeps a configured site's password unless a new one is typed twice", async () => {
    const dialog = renderDialog(makeWebsite({ requires_http_auth: true }) as unknown as Website);
    const password = field(dialog, /^Lösenord/);

    expect(password.getAttribute("aria-required")).toBeNull();
    const hint = within(dialog).getByText("Lämna tomt för att behålla nuvarande lösenord");
    expect(password.getAttribute("aria-describedby")).toContain(hint.id);
    await expectNoAxeViolations(document.body);

    fireEvent.change(password, { target: { value: "hemlis-3" } });
    expect(field(dialog, /^Bekräfta lösenord/).getAttribute("aria-required")).toBe("true");
    expect(
      (within(dialog).getByRole("button", { name: "Spara ändringar" }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
  });
});
