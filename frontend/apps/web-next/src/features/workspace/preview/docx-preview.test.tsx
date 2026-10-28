// @vitest-environment jsdom
import { cleanup, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NonceProvider } from "@/components/providers/nonce";
import { renderInApp } from "@/test/render";
import { DocxPreview } from "./docx-preview";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

// The renderer's output: its stylesheet, and the pages with links of every kind.
vi.mock("docx-preview", () => ({
  parseAsync: async () => ({}),
  renderDocument: async () => {
    const style = document.createElement("style");
    style.textContent = ".docx { color: inherit; }";
    const wrapper = document.createElement("div");
    wrapper.className = "docx-wrapper";
    wrapper.innerHTML = `<section class="docx"><style>p {}</style>
      <a href="https://example.se/a">extern</a>
      <a href="#bilaga">intern</a>
      <a href="java&#10;script:alert(1)">skript</a>
    </section>`;
    return [style, wrapper];
  }
}));

afterEach(cleanup);

it("renders into a script-less frame whose every style carries the nonce, with safe links", async () => {
  const onReady = vi.fn();
  const { container } = renderInApp(
    <NonceProvider nonce="r4nd0m">
      <DocxPreview bytes={new ArrayBuffer(8)} title="avtal.docx" onReady={onReady} />
    </NonceProvider>
  );
  const frame = container.querySelector("iframe")!;
  expect(frame.getAttribute("sandbox")).toBe(
    "allow-same-origin allow-popups allow-popups-to-escape-sandbox"
  );
  // jsdom gives only the page's window a CSS namespace; a browser's frame has its own.
  Object.defineProperty(frame.contentWindow, "CSS", { value: window.CSS });
  // The frame renders once its shell document has loaded.
  await waitFor(() => expect(onReady).toHaveBeenCalledOnce());

  const frameDocument = frame.contentDocument!;
  const styles = [...frameDocument.querySelectorAll("style")];
  expect(styles).toHaveLength(3);
  expect(styles.map((style) => style.getAttribute("nonce"))).toEqual([
    "r4nd0m",
    "r4nd0m",
    "r4nd0m"
  ]);
  // The frame's own rules come last in its head, so they win.
  expect(frameDocument.head.lastElementChild?.textContent).toContain(
    "::highlight(file-preview-quote)"
  );

  const [external, internal, script] = [...frameDocument.querySelectorAll("a")];
  expect(external?.target).toBe("_blank");
  expect(external?.rel).toBe("noopener noreferrer");
  expect(internal?.getAttribute("href")).toBe("#bilaga");
  expect(internal?.target).toBe("");
  expect(script?.hasAttribute("href")).toBe(false);
});
