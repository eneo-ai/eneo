import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import WidgetPublishedNotice from "./WidgetPublishedNotice.svelte";

describe("WidgetPublishedNotice", () => {
  test("says the assistant is public and links to the widget settings", async () => {
    render(WidgetPublishedNotice, { href: "/spaces/s1/assistants/a1/widget" });
    const note = page.getByRole("note", { name: "widget_admin_assistant_notice_title" });
    await expect.element(note).toBeVisible();
    await expect.element(note).toHaveTextContent("widget_admin_assistant_notice_body");
    await expect
      .element(page.getByRole("link", { name: "widget_admin_open" }))
      .toHaveAttribute("href", "/spaces/s1/assistants/a1/widget");
  });
});
