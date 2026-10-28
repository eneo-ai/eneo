// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ContinueSignedIn } from "./continue-signed-in";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("loads the page as a new document, in place of /login", () => {
  const replace = vi.fn();
  vi.stubGlobal("location", { ...window.location, replace });

  render(<ContinueSignedIn href="/spaces/abc" />);

  expect(replace).toHaveBeenCalledExactlyOnceWith("/spaces/abc");
});
