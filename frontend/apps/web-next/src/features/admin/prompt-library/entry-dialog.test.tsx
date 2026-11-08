// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { EntryDialog } from "./entry-dialog";

vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: vi.fn() } }));

it("gives the prompt name its native 200-character limit", () => {
  renderInApp(<EntryDialog entry={null} open onOpenChange={vi.fn()} onShowHistory={vi.fn()} />);
  const name = screen.getByRole("textbox", { name: /^Namn/ }) as HTMLInputElement;
  expect(name.maxLength).toBe(200);
});
