// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SpaceModelSelect, type SelectableModel } from "./space-model-select";

afterEach(cleanup);

const models: SelectableModel[] = [
  { id: "claude", name: "Claude", org: "anthropic" },
  { id: "gpt", name: "GPT", org: "openai" },
  { id: "blocked", name: "Blocked", org: "openai", meets_security_classification: false }
];

function show(onChange = vi.fn()) {
  const view = renderInApp(
    <SpaceModelSelect
      kind="completion"
      title="Chattmodeller"
      description="Används när assistenter skriver svar."
      models={models}
      selectedIds={["claude"]}
      pending={false}
      onChange={onChange}
    />
  );
  return { ...view, onChange };
}

describe("SpaceModelSelect", () => {
  it("summarizes the selection and keeps model controls hidden until opened", async () => {
    const { container } = show();

    expect(screen.getByRole("heading", { name: "Chattmodeller" })).toBeTruthy();
    expect(screen.getByText("1 modell vald")).toBeTruthy();
    expect(screen.getByText("Claude")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "GPT" })).toBeNull();

    const choose = screen.getByRole("button", { name: "Välj Chattmodeller" });
    expect(choose.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(choose);
    expect(screen.getByRole("button", { name: "Dölj Chattmodeller" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Claude" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("preserves model selection and security restrictions inside vendor groups", () => {
    const { onChange } = show();
    fireEvent.click(screen.getByRole("button", { name: "Välj Chattmodeller" }));
    fireEvent.click(screen.getByRole("button", { name: "Openai" }));

    fireEvent.click(screen.getByRole("switch", { name: "GPT" }));
    expect(onChange).toHaveBeenCalledWith(["claude", "gpt"]);
    expect(screen.getByRole("switch", { name: "Blocked" }).hasAttribute("disabled")).toBe(true);
  });
});
