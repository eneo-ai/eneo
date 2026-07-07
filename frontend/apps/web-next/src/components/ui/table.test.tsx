// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Table, TableBody, TableCell, TableRow } from "./table";

it("activates actionable rows with pointer and keyboard", () => {
  const onRowAction = vi.fn();

  render(
    <Table>
      <TableBody>
        <TableRow aria-label="Open details" onRowAction={onRowAction}>
          <TableCell>Details</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );

  const row = screen.getByRole("row", { name: "Open details" });
  fireEvent.click(row);
  fireEvent.keyDown(row, { key: "Enter" });
  fireEvent.keyDown(row, { key: " " });
  fireEvent.keyDown(row, { key: "Escape" });

  expect(row.getAttribute("tabindex")).toBe("0");
  expect(onRowAction).toHaveBeenCalledTimes(3);
});
