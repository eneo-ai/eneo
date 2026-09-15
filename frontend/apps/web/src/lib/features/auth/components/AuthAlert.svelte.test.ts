import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test } from "vitest";
import { createRawSnippet } from "svelte";
import "../../../../app.css";

import AuthAlert from "./AuthAlert.svelte";

const body = createRawSnippet(() => ({ render: () => "<p>Body text</p>" }));

describe("auth alert", () => {
  test("errors interrupt, other tones are polite status regions", async () => {
    render(AuthAlert, { tone: "error", title: "Something failed", children: body });
    const alert = page.getByRole("alert");
    await expect.element(alert).toHaveTextContent("Something failed");
    await expect.element(alert).toHaveTextContent("Body text");

    render(AuthAlert, { tone: "success", children: body });
    await expect.element(page.getByRole("status")).toHaveTextContent("Body text");
  });

  test("can receive programmatic focus for error summaries", async () => {
    const { container } = render(AuthAlert, {
      tone: "error",
      id: "summary",
      tabindex: -1,
      children: body
    });
    const el = container.querySelector<HTMLElement>("#summary");
    el?.focus();
    await expect.element(page.getByRole("alert")).toHaveFocus();
  });
});
