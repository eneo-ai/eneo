// @vitest-environment jsdom
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { Widget } from "./autosave";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { WidgetPreview } from "./widget-preview";

const PREVIEW_TOKEN_PATH = "/api/v1/widgets/{id}/preview-token/";
const WITHHELD =
  "Precis som besökarnas turer når förhandsvisningen bara de verktyg på MCP-servrar utanför Eneo som en administratör har bekräftat och organisationen tillåter.";

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    public_id: "wgt_aaaaaaaaaaaaaaaaaaaaaa",
    status: "draft",
    token_generation: 1,
    revision: 3,
    language: "sv",
    theme: { primary_color: "#1F4E79", radius: 12, color_scheme: "auto" },
    activation_blockers: [],
    external_tools: [],
    external_tools_acknowledged: true,
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides
  } as unknown as Widget;
}

/** Every mint stays pending until the test answers it. */
function mintOnRequest() {
  const answers: Array<(minted: { token: string; expires_in: number }) => void> = [];
  api.POST.mockImplementation(
    () =>
      new Promise((resolve) =>
        answers.push((minted) => resolve({ data: minted, response: new Response("{}") }))
      )
  );
  return answers;
}

const mints = () => api.POST.mock.calls.filter(([path]) => path === PREVIEW_TOKEN_PATH).length;

afterEach(() => {
  api.POST.mockReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("WidgetPreview", () => {
  it("of a paused widget asks for no token and says why there is nothing to show", () => {
    mintOnRequest();
    renderInApp(<WidgetPreview widget={widget({ status: "paused" })} />);
    expect(
      screen.getByText(
        "En pausad widget förhandsgranskas inte: pausen stänger alla vägar in till chattsidan. Återuppta widgeten för att förhandsgranska den."
      )
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ladda om" }).hasAttribute("disabled")).toBe(true);
    expect(api.POST).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("a save that rotates the tokens loads no frame on the revoked one", async () => {
    const answers = mintOnRequest();
    const view = renderInApp(<WidgetPreview widget={widget()} />);
    expect(mints()).toBe(1);
    await act(async () => answers[0]!({ token: "first", expires_in: 3600 }));
    expect(document.querySelector("iframe")?.getAttribute("src")).toContain("#preview=first");

    // The save's new updated_at would reload the frame on the old token.
    view.rerender(
      <WidgetPreview widget={widget({ token_generation: 2, updated_at: "2026-09-21T10:05:00Z" })} />
    );
    await waitFor(() => expect(mints()).toBe(2));
    expect(document.querySelector("iframe")).toBeNull();

    await act(async () => answers[1]!({ token: "second", expires_in: 3600 }));
    expect(document.querySelector("iframe")?.getAttribute("src")).toContain("#preview=second");
  });

  it("a renewal that falls due on a hidden page waits until it is shown", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const answers = mintOnRequest();
    renderInApp(<WidgetPreview widget={widget()} />);
    expect(mints()).toBe(1);
    await act(async () => answers[0]!({ token: "first", expires_in: 3600 }));
    expect(document.querySelector("iframe")?.getAttribute("src")).toContain("#preview=first");

    // Every mint is audited: a page nobody looks at mints no more.
    await act(async () => vi.advanceTimersByTimeAsync(7_200_000));
    expect(mints()).toBe(1);

    visibility.mockReturnValue("visible");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(mints()).toBe(2);
  });

  it.each([
    { case: "unacknowledged tools", overrides: { external_tools_acknowledged: false }, note: true },
    {
      case: "tools the policy forbids",
      overrides: { activation_blockers: ["external_tools_not_allowed"] },
      note: true
    },
    { case: "acknowledged, allowed tools", overrides: {}, note: false }
  ])("says whether it runs without $case", ({ overrides, note }) => {
    mintOnRequest();
    renderInApp(
      <WidgetPreview
        widget={widget({
          external_tools: [{ id: "m1", name: "Ärenden", tools: [{ id: "t1", name: "Sök" }] }],
          ...overrides
        } as Partial<Widget>)}
      />
    );
    expect(screen.queryByText(WITHHELD) !== null).toBe(note);
  });
});
