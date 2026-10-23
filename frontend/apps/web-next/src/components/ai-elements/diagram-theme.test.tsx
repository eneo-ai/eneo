// @vitest-environment jsdom
import type { MermaidConfig } from "@streamdown/mermaid";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { ThemeProvider, useTheme } from "next-themes";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { MessageResponse } from "./message";

// Only SVG layout is replaced: the theme provider, both Streamdown renderers
// and their memo/context boundaries are real. Browsers exercise Mermaid itself.
vi.mock("@streamdown/mermaid", () => ({
  createMermaidPlugin: () => ({
    name: "mermaid",
    type: "diagram",
    language: "mermaid",
    getMermaid: (config: MermaidConfig) => ({
      render: async () => ({
        svg: `<svg viewBox="0 0 100 40"><rect width="100" height="40" fill="${config.theme === "dark" ? "black" : "white"}"/></svg>`
      })
    })
  })
}));

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(private callback: IntersectionObserverCallback) {}
      observe(target: Element) {
        this.callback(
          [{ isIntersecting: true, target } as IntersectionObserverEntry],
          this as unknown as IntersectionObserver
        );
      }
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

function ThemeToggle() {
  const { setTheme } = useTheme();
  return <button onClick={() => setTheme("dark")}>Mörkt tema</button>;
}

it("updates an existing diagram when the colour mode changes without replacing the answer", async () => {
  const { container } = renderInApp(
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <ThemeToggle />
      <MessageResponse isAnimating={false}>{"```mermaid\ngraph LR\nA --> B\n```"}</MessageResponse>
    </ThemeProvider>
  );
  const answer = container.querySelector(".eneo-answer");
  await waitFor(() =>
    expect(container.querySelector("svg rect")?.getAttribute("fill")).toBe("white")
  );
  fireEvent.click(screen.getByRole("button", { name: "Mörkt tema" }));
  await waitFor(() =>
    expect(container.querySelector("svg rect")?.getAttribute("fill")).toBe("black")
  );
  expect(container.querySelector(".eneo-answer")).toBe(answer);
});
