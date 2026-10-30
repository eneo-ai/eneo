// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import path from "node:path";
import { CommandPalette } from "@astryxdesign/core/CommandPalette";
import { DropdownMenu, DropdownMenuItem } from "@astryxdesign/core/DropdownMenu";
import { Pagination } from "@astryxdesign/core/Pagination";
import { SideNav, SideNavItem } from "@astryxdesign/core/SideNav";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { createStaticSource } from "@astryxdesign/core/Typeahead";
import { fireEvent, screen } from "@testing-library/react";
import postcss, { type AtRule, type Rule } from "postcss";
import { describe, expect, it } from "vitest";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { renderInApp } from "@/test/render";

// The forced-colours rules in globals.css (section 10) target Astryx's and
// the legacy components' markup; these checks fail when an upgrade renames
// what they select, before the rules silently stop applying.
const css = readFileSync(path.join(import.meta.dirname, "globals.css"), "utf8");
const selectors: string[] = [];
postcss.parse(css).walkAtRules("media", (media: AtRule) => {
  if (media.params !== "(forced-colors: active)") return;
  media.walkRules((rule: Rule) => {
    selectors.push(...rule.selectors);
  });
});

function matching(selector: string): Element[] {
  expect(selectors).toContain(selector);
  return [...document.querySelectorAll(selector)];
}

describe("forced-colours rules", () => {
  it("find the current nav item's label, and only its text", () => {
    renderInApp(
      <SideNav aria-label="Navigering">
        <SideNavItem label="Modeller" href="/admin/models" isSelected />
        <SideNavItem label="Användare" href="/admin/users" />
      </SideNav>
    );
    const [label, ...others] = matching(
      '.astryx-side-nav-item[data-selected="selected"] > span:not(:has(*))'
    );
    expect(label?.textContent).toBe("Modeller");
    expect(others).toEqual([]);
  });

  it("find the selected tab's bar", () => {
    renderInApp(
      <TabList value="b" onChange={() => {}} aria-label="Flikar">
        <Tab value="a" label="Samlingar" />
        <Tab value="b" label="Webbplatser" />
      </TabList>
    );
    const [bar, ...others] = matching('.astryx-tab-indicator[data-selected="selected"]');
    // (Astryx repeats the label in a hidden sizer.)
    expect(bar?.closest(".astryx-tab")?.textContent).toContain("Webbplatser");
    expect(others).toEqual([]);
  });

  it("find the focused menu item", async () => {
    renderInApp(
      <DropdownMenu button={{ label: "Meny" }}>
        <DropdownMenuItem label="Redigera" onClick={() => {}} />
        <DropdownMenuItem label="Ta bort" onClick={() => {}} />
      </DropdownMenu>
    );
    fireEvent.click(screen.getByRole("button", { name: "Meny" }));
    const item = await screen.findByRole("menuitem", { name: "Ta bort" });
    item.focus();
    expect(matching(".astryx-dropdown-menu-item:focus")).toEqual([item]);
  });

  it("find the palette's active option", async () => {
    renderInApp(
      <CommandPalette
        isOpen
        onOpenChange={() => {}}
        label="Sök"
        searchSource={createStaticSource([
          { id: "a", label: "Upphandlingsassistenten" },
          { id: "b", label: "Avtalsgranskaren" }
        ])}
      />
    );
    await screen.findByRole("option", { name: "Upphandlingsassistenten" });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    const active = matching('.astryx-command-palette-item[aria-selected="true"]');
    expect(active).toHaveLength(1);
    expect(active[0]?.id).toBe(screen.getByRole("combobox").getAttribute("aria-activedescendant"));
  });

  it("find the current page and the legacy active tab", () => {
    renderInApp(
      <>
        <Pagination page={2} onChange={() => {}} totalItems={60} pageSize={20} />
        <Tabs defaultValue="tokens">
          <TabsList>
            <TabsTrigger value="tokens">Tokens</TabsTrigger>
            <TabsTrigger value="users">Användare</TabsTrigger>
          </TabsList>
        </Tabs>
      </>
    );
    expect(
      matching('.astryx-pagination [aria-current="page"]').map((el) => el.textContent)
    ).toEqual(["2"]);
    expect(
      matching('[data-slot="tabs-trigger"][data-state="active"]').map((el) => el.textContent)
    ).toEqual(["Tokens"]);
  });
});
