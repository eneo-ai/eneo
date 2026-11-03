// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Tabs, TabsList, TabsTrigger } from "./tabs";

// jsdom applies no CSS, so this reads the classes: the selected tab is the
// shared raised plate (eneo-theme.contrast.test.ts holds its contrast), with no
// colour of its own per mode. Names are built at runtime so this file does not
// become a Tailwind source for them.
const active = (utility: string) => ["data-[state=active]:", utility].join("");

it("draws the selected tab as the shared segment plate", () => {
  render(
    <Tabs defaultValue="run">
      <TabsList>
        <TabsTrigger value="run">Kör</TabsTrigger>
        <TabsTrigger value="result">Resultat</TabsTrigger>
      </TabsList>
    </Tabs>
  );
  const selected = screen.getByRole("tab", { name: "Kör" }).className;
  expect(selected).toContain(active(["bg", "ax-segment-selected"].join("-")));
  expect(selected).toContain(active(["border", "ax-segment-selected-edge"].join("-")));
  expect(selected).not.toMatch(/(^|\s)dark:/);
});
