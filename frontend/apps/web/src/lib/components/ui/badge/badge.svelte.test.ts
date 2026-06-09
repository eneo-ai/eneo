import { createRawSnippet } from "svelte";
import { describe, expect, it } from "vitest";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { Badge } from "./index.js";

// Reference component test: renders a real Svelte 5 component in Chromium and
// asserts on the resulting DOM. The `.svelte.test.ts` suffix routes this file to
// the browser-mode "client" Vitest project (see vite.config.ts). Use this as the
// template for testing any component.
const label = (text: string) => createRawSnippet(() => ({ render: () => `<span>${text}</span>` }));

describe("Badge", () => {
  it("renders the content passed via the children snippet", async () => {
    render(Badge, { children: label("Active") });

    await expect.element(page.getByText("Active")).toBeVisible();
  });

  it("applies variant-specific styling", async () => {
    render(Badge, { variant: "destructive", children: label("Failed") });

    const root = page.getByText("Failed").element().closest('[data-slot="badge"]');
    expect(root?.className).toContain("text-destructive");
  });
});
