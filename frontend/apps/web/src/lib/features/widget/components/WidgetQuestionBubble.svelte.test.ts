import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";
import WidgetQuestionBubble from "./WidgetQuestionBubble.svelte";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

describe("WidgetQuestionBubble", () => {
  test("wraps a pasted address inside a narrow panel instead of scrolling sideways", async () => {
    const { container } = render(WidgetQuestionBubble, {
      text: "https://www.sundsvall.se/download/18.1bd1b4dd1734a2cbd0c4f6d/1596717431245/Taxa_plan_och_bygglov_2024.pdf"
    });
    container.style.width = "240px";

    const bubble = container.querySelector("p")!;
    await vi.waitFor(() => expect(bubble.getBoundingClientRect().width).toBeLessThan(240));
    expect(bubble.scrollWidth).toBeLessThanOrEqual(bubble.clientWidth);
    expect(container.scrollWidth).toBeLessThanOrEqual(240);
  });
});
