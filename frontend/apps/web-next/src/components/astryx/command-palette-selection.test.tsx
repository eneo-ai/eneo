// @vitest-environment jsdom
import { CommandPalette } from "@astryxdesign/core/CommandPalette";
import { createStaticSource } from "@astryxdesign/core/Typeahead";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";

// Guards frontend/patches/@astryxdesign%2Fcore@0.6.3.patch. Unpatched, Astryx
// marks only a picked value as selected, so every highlighted option is
// exposed as "not selected". After an Astryx upgrade bun silently skips a
// stale patch; this test then fails: recreate the patch with
// `bun patch @astryxdesign/core` (or drop it if Astryx fixed the item).
it("exposes the highlighted palette option as the selected one", async () => {
  renderInApp(
    <CommandPalette
      isOpen
      onOpenChange={() => {}}
      label="Sök"
      searchSource={createStaticSource([
        { id: "spaces", label: "Ytor" },
        { id: "assistants", label: "Assistenter" }
      ])}
    />
  );

  const input = await screen.findByRole("combobox");
  await screen.findByRole("option", { name: "Assistenter" });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "ArrowDown" });

  await waitFor(() => {
    const active = document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(active?.textContent).toBe("Assistenter");
    expect(active?.getAttribute("aria-selected")).toBe("true");
  });
  expect(screen.getByRole("option", { name: "Ytor" }).getAttribute("aria-selected")).toBe("false");
});
