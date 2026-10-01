// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SpaceModelSelect, type SelectableModel } from "./space-model-select";

afterEach(cleanup);

const models: SelectableModel[] = [
  { id: "north-1", name: "Aurora", org: "Nord AI", provider_type: "azure" },
  { id: "north-2", name: "Borealis", org: "Nord AI", provider_type: "azure" },
  { id: "south-1", name: "Cumulus", org: "Syd AI" },
  { id: "south-2", name: "Cirrus", org: "Syd AI" },
  { id: "south-3", name: "Stratus", org: "Syd AI" },
  { id: "south-4", name: "Nimbus", org: "Syd AI" },
  { id: "south-5", name: "Altus", org: "Syd AI" }
];

/** Model controls sit behind the card's "choose" button. */
function openCard() {
  fireEvent.click(screen.getByRole("button", { name: "Välj Chattmodeller" }));
}

function renderModels(
  available: SelectableModel[],
  { selectedIds = [] as string[], onChange = vi.fn() } = {}
) {
  const view = renderInApp(
    <SpaceModelSelect
      models={available}
      selectedIds={selectedIds}
      title="Chattmodeller"
      description="Välj modeller"
      kind="completion"
      onChange={onChange}
    />
  );
  return { ...view, onChange };
}

function StatefulModels({
  available,
  initialSelection = []
}: {
  available: SelectableModel[];
  initialSelection?: string[];
}) {
  const [selectedIds, setSelectedIds] = useState(initialSelection);
  return (
    <SpaceModelSelect
      models={available}
      selectedIds={selectedIds}
      title="Chattmodeller"
      description="Välj modeller"
      kind="completion"
      onChange={(change) => setSelectedIds((current) => change(current))}
    />
  );
}

describe("SpaceModelSelect", () => {
  it("summarizes the selection and keeps model controls hidden until opened", async () => {
    const { container } = renderModels(models, { selectedIds: ["north-1"] });

    expect(screen.getByRole("heading", { name: "Chattmodeller" })).toBeTruthy();
    expect(screen.getByText("1 modell vald")).toBeTruthy();
    expect(screen.getByText("Aurora")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Borealis" })).toBeNull();

    const choose = screen.getByRole("button", { name: "Välj Chattmodeller" });
    expect(choose.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(choose);
    expect(screen.getByRole("button", { name: "Dölj Chattmodeller" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Aurora" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("reports a selection change as a function of the current selection", () => {
    const { onChange } = renderModels(models, { selectedIds: ["north-1"] });
    openCard();

    fireEvent.click(screen.getByRole("switch", { name: "Borealis" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const change = onChange.mock.calls[0]![0] as (current: string[]) => string[];
    expect(change(["north-1"])).toEqual(["north-1", "north-2"]);
    expect(change(["north-1", "north-2"])).toEqual(["north-1"]);
  });

  it("localizes the group for a model without a provider", () => {
    renderModels([{ id: "independent", name: "Fristående modell" }]);
    openCard();
    expect(screen.getByText("Övriga")).toBeTruthy();
  });

  it("finds a provider, explains no matches and returns focus when search is cleared", async () => {
    const { container } = renderModels(models);
    openCard();
    const search = screen.getByRole("textbox", { name: "Sök modeller och leverantörer" });

    fireEvent.change(search, { target: { value: "nord ai" } });
    expect(screen.getByText("Aurora")).toBeTruthy();
    expect(screen.getByText("Borealis")).toBeTruthy();
    expect(screen.queryByText("Cumulus")).toBeNull();

    fireEvent.change(search, { target: { value: "azure" } });
    expect(screen.getByText("Aurora")).toBeTruthy();
    expect(screen.queryByText("Cumulus")).toBeNull();

    fireEvent.change(search, { target: { value: "saknas" } });
    expect(screen.getByText("Inga modeller matchar sökningen.")).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Rensa modellsökningen" }));

    expect((search as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(search);
    expect(screen.queryByText("Inga modeller matchar sökningen.")).toBeNull();
  });

  it("explains an unavailable model in reading order and on its switch", async () => {
    const { container } = renderModels([
      {
        id: "restricted",
        name: "Skyddad modell",
        org: "Nord AI",
        meets_security_classification: false
      }
    ]);
    openCard();

    const reason = screen.getByText(
      "Denna modell uppfyller inte den valda säkerhetsklassificeringen"
    );
    const toggle = screen.getByRole("switch", { name: "Skyddad modell" });
    expect(toggle.hasAttribute("disabled")).toBe(true);
    expect(toggle.getAttribute("aria-describedby")).toBe(reason.id);
    await expectNoAxeViolations(container);
  });

  it("keeps a group and its focused switch open when the last model is deselected", () => {
    renderInApp(<StatefulModels available={models} initialSelection={["north-1"]} />);
    openCard();
    const group = screen.getByRole("button", { name: "Nord AI" });
    const toggle = screen.getByRole("switch", { name: "Aurora" });
    toggle.focus();

    fireEvent.click(toggle);

    expect(toggle.getAttribute("data-state")).toBe("unchecked");
    expect(group.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(toggle);
  });

  it("keeps closed group controls out of the keyboard order during its exit", () => {
    renderInApp(<StatefulModels available={models} />);
    openCard();
    const group = screen.getByRole("button", { name: "Nord AI" });
    expect(group.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(group);
    expect(group.getAttribute("aria-expanded")).toBe("true");
    const contentId = group.getAttribute("aria-controls");
    if (!contentId) throw new Error("Collapsible trigger has no content id");
    expect(document.getElementById(contentId)?.hasAttribute("inert")).toBe(false);

    group.focus();
    fireEvent.click(group);
    expect(group.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(group);
    expect(document.getElementById(contentId)?.hasAttribute("inert")).toBe(true);
    expect(screen.queryByRole("switch", { name: "Aurora" })).toBeNull();
  });
});
