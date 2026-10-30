// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { router, setRoute } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import { inAppLinkTarget, useLeaveConfirmation } from "./use-leave-confirmation";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

function Page({ active }: { active: boolean }) {
  const guard = useLeaveConfirmation(active);
  return (
    <>
      <a href="/admin/users?tab=all">Users</a>
      <a href="#flow-files">Files</a>
      <output>{guard.pendingHref ?? "none"}</output>
      <button type="button" onClick={guard.stay}>
        Stay
      </button>
      <button type="button" onClick={guard.leave}>
        Leave
      </button>
    </>
  );
}

const pending = () => screen.getByRole("status").textContent;
const answer = (name: "Stay" | "Leave") => fireEvent.click(screen.getByRole("button", { name }));

/** Clicks a link and says whether the browser would follow it (jsdom is kept from trying). */
function click(name: string): boolean {
  let followed = false;
  const record = (event: Event) => {
    followed = !event.defaultPrevented;
    event.preventDefault();
  };
  window.addEventListener("click", record);
  fireEvent.click(screen.getByRole("link", { name }));
  window.removeEventListener("click", record);
  return followed;
}

describe("useLeaveConfirmation", () => {
  it("holds a click on a link to another page until the user answers", () => {
    setRoute("/admin/flow-settings");
    window.history.replaceState(null, "", "/admin/flow-settings");
    renderInApp(<Page active />);

    expect(click("Users")).toBe(false);
    expect(pending()).toBe("/admin/users?tab=all");

    answer("Stay");
    expect(pending()).toBe("none");
    expect(router.push).not.toHaveBeenCalled();

    click("Users");
    answer("Leave");
    expect(router.push).toHaveBeenCalledWith("/admin/users?tab=all");
    expect(pending()).toBe("none");
  });

  it("lets a link to a place on the same page through", () => {
    window.history.replaceState(null, "", "/admin/flow-settings");
    renderInApp(<Page active />);
    expect(click("Files")).toBe(true);
    expect(pending()).toBe("none");
  });

  it("holds nothing without unsaved changes", () => {
    window.history.replaceState(null, "", "/admin/flow-settings");
    renderInApp(<Page active={false} />);
    expect(click("Users")).toBe(true);
    expect(pending()).toBe("none");
  });

  it("leaves modified clicks, other windows, downloads and other sites to the browser", () => {
    const location = new URL("http://localhost/admin/flow-settings") as unknown as Location;
    const link = (attributes: Record<string, string>) => {
      const anchor = document.createElement("a");
      for (const [name, value] of Object.entries(attributes)) anchor.setAttribute(name, value);
      document.body.append(anchor);
      return anchor;
    };
    const clickOn = (target: Element, init: MouseEventInit = {}) => {
      const event = new MouseEvent("click", { bubbles: true, cancelable: true, ...init });
      Object.defineProperty(event, "target", { value: target });
      return event;
    };

    const internal = link({ href: "/spaces" });
    expect(inAppLinkTarget(clickOn(internal), location)).toBe("/spaces");
    expect(inAppLinkTarget(clickOn(internal, { metaKey: true }), location)).toBeNull();
    expect(inAppLinkTarget(clickOn(internal, { button: 1 }), location)).toBeNull();
    expect(inAppLinkTarget(clickOn(link({ href: "/spaces", target: "_blank" })), location)).toBe(
      null
    );
    expect(inAppLinkTarget(clickOn(link({ href: "/report.pdf", download: "" })), location)).toBe(
      null
    );
    expect(inAppLinkTarget(clickOn(link({ href: "https://example.org/" })), location)).toBeNull();
    expect(inAppLinkTarget(clickOn(document.body), location)).toBeNull();
  });
});
