// @vitest-environment jsdom
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { Button } from "./button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "./dropdown-menu";

afterEach(cleanup);

it("keeps the page's Astryx buttons named while a menu is open, and closes with Escape", async () => {
  renderInApp(
    <>
      <AstryxButton label="Spara sidan" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button>Åtgärder</Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Byt namn</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
  const trigger = screen.getByRole("button", { name: "Åtgärder" });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  const menu = await screen.findByRole("menu");

  expect(screen.getByRole("button", { name: "Spara sidan" })).toBeTruthy();
  await expectNoAxeViolations(document.body);

  fireEvent.keyDown(menu, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  expect(document.activeElement).toBe(trigger);
});
