// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { MessageResponse } from "./message";

// The diagram renderer arrives on demand; here it cannot be fetched (its chunk
// is gone after a deploy).
const state = vi.hoisted(() => ({ loads: 0 }));
vi.mock("./diagram", () => {
  state.loads += 1;
  throw new Error("Failed to fetch dynamically imported module");
});

afterEach(cleanup);

it("keeps a diagram as code when its renderer cannot load, and tries again later", async () => {
  const first = renderInApp(
    <MessageResponse isAnimating={false}>{"```mermaid\ngraph LR\nA --> B\n```"}</MessageResponse>
  );
  await waitFor(() => expect(state.loads).toBe(1));
  expect(first.container.textContent).toContain("A --> B");
  expect(screen.queryByRole("button", { name: "Visa i helskärm" })).toBeNull();

  // The next diagram rendered loads the renderer again.
  renderInApp(
    <MessageResponse isAnimating={false}>{"```mermaid\ngraph LR\nC --> D\n```"}</MessageResponse>
  );
  await waitFor(() => expect(state.loads).toBe(2));
  expect(first.container.textContent).toContain("A --> B");
});
