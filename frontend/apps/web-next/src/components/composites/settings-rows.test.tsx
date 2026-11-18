// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { SettingsGroup } from "./settings-rows";

afterEach(cleanup);

/** The header line that holds the title block and the header's actions. */
function headerLine(title: string) {
  return screen.getByRole("heading", { name: title }).parentElement!.parentElement!;
}

it("centres a lone title on its header action's line", () => {
  renderInApp(
    <SettingsGroup
      title="Instruktioner"
      headerEnd={<button type="button">Visa prompthistorik</button>}
    >
      <p>Prompt</p>
    </SettingsGroup>
  );
  expect(headerLine("Instruktioner").className).toContain("items-center");
  expect(headerLine("Instruktioner").className).not.toContain("items-start");
});

it("keeps the action at the top beside a title and a description", () => {
  renderInApp(
    <SettingsGroup
      title="API-nycklar"
      description="Nycklar som bara gäller den här resursen."
      headerEnd={<button type="button">Skapa nyckel</button>}
    >
      <p>Inga nycklar</p>
    </SettingsGroup>
  );
  expect(headerLine("API-nycklar").className).toContain("items-start");
});
