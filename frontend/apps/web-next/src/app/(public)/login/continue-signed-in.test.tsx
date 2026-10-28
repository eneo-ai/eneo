// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ContinueSignedIn } from "./continue-signed-in";

const events = vi.hoisted(() => [] as string[]);
vi.mock("@/lib/session/identity-broadcast", () => ({
  announceIdentityChange: () => events.push("announce")
}));

afterEach(() => {
  vi.unstubAllGlobals();
  events.length = 0;
});

it("tells the other tabs, then loads the page as a new document in place of /login", () => {
  const replace = vi.fn((href: string) => events.push(`replace ${href}`));
  vi.stubGlobal("location", { ...window.location, replace });

  render(<ContinueSignedIn href="/spaces/abc" />);

  expect(events).toEqual(["announce", "replace /spaces/abc"]);
});
