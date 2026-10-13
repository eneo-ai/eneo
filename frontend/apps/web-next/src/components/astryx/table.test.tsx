// @vitest-environment jsdom
import { proportional } from "@astryxdesign/core/Table";
import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { Table } from "./table";

type Row = { id: string; name: string };
const rows: Row[] = [{ id: "1", name: "Upphandlingspolicy" }];
const columns = [{ key: "name" as const, header: "Namn", width: proportional(1) }];

it("names the table's scroll region after the table, not just 'Tabell'", async () => {
  const { container } = renderInApp(
    <Table data={rows} columns={columns} idKey="id" aria-label="Samlingar" />
  );

  expect(screen.getByRole("table", { name: "Samlingar" })).toBeTruthy();
  expect(screen.getByRole("group", { name: "Samlingar" })).toBeTruthy();
  await expectNoAxeViolations(container);
});

it("names both by the heading that names the table", () => {
  renderInApp(
    <>
      <h2 id="knowledge-heading">Kunskap</h2>
      <Table data={rows} columns={columns} idKey="id" aria-labelledby="knowledge-heading" />
    </>
  );

  expect(screen.getByRole("table", { name: "Kunskap" })).toBeTruthy();
  expect(screen.getByRole("group", { name: "Kunskap" })).toBeTruthy();
});

it("won't type-check without a name", () => {
  // @ts-expect-error a table needs aria-label or aria-labelledby
  void (<Table data={rows} columns={columns} idKey="id" />);
});
