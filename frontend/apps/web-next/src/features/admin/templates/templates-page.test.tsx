// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const template = (id: string, name: string) => ({
  id,
  name,
  category: "Upphandling",
  completion_model_name: null,
  usage_count: 2,
  is_default: false,
  original_snapshot: null,
  deleted_at: null
});

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    POST: post,
    GET: (path: string) => {
      const items =
        path === "/api/v1/admin/templates/assistants/"
          ? [template("a1", "Upphandlingsassistent")]
          : path === "/api/v1/admin/templates/apps/"
            ? [template("p1", "Protokollsammanfattare")]
            : path.endsWith("/deleted")
              ? [template("d1", "Gammal mall")]
              : [];
      return Promise.resolve({ data: { items }, response: new Response("{}") });
    }
  }
}));

import { TemplatesPage } from "./templates-page";

afterEach(() => {
  cleanup();
  post.mockReset();
});

describe("TemplatesPage", () => {
  it("names each tab's table after the tab", async () => {
    const { container } = renderInApp(<TemplatesPage />);

    const assistants = await screen.findByRole("table", { name: "Assistenter" });
    expect(within(assistants).getByText("Upphandlingsassistent")).toBeTruthy();
    // Each row's menu says whose it is.
    expect(
      within(assistants).getByRole("button", { name: "Fler åtgärder för Upphandlingsassistent" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    // Radix tabs switch on mouse down.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Appar" }));
    const apps = await screen.findByRole("table", { name: "Appar" });
    expect(within(apps).getByText("Protokollsammanfattare")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Borttagna mallar" }));
    const deleted = await screen.findByRole("table", { name: "Borttagna mallar" });
    expect(within(deleted).getAllByText("Gammal mall")).toHaveLength(2);
  });

  it("keeps focus on a busy Återställ and restores once", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(<TemplatesPage />);
    fireEvent.mouseDown(await screen.findByRole("tab", { name: "Borttagna mallar" }));
    const deleted = await screen.findByRole("table", { name: "Borttagna mallar" });
    const restore = within(deleted).getAllByRole("button", { name: "Återställ" })[0]!;
    restore.focus();

    fireEvent.click(restore);

    await waitFor(() => expect(restore.getAttribute("aria-busy")).toBe("true"));
    expect(restore.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(restore);
    fireEvent.click(restore);
    expect(post).toHaveBeenCalledTimes(1);
  });
});
