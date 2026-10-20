// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { StepKindPicker } from "./step-kind-picker";

afterEach(cleanup);

describe("StepKindPicker", () => {
  it("lists the six kinds with one line each and hands back the one picked", async () => {
    const onPick = vi.fn();
    renderInApp(<StepKindPicker label="Infoga steg efter 2" onPick={onPick} iconOnly />);
    fireEvent.click(screen.getByRole("button", { name: "Infoga steg efter 2" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("Modell"),
      expect.stringContaining("Text"),
      expect.stringContaining("Dokument"),
      expect.stringContaining("Granskning"),
      expect.stringContaining("Transkribering"),
      expect.stringContaining("Funktion")
    ]);
    expect(items[3]!.textContent).toContain(
      "Pausar flödet tills en person har godkänt eller ändrat ett resultat."
    );
    fireEvent.click(items[3]!);
    expect(onPick).toHaveBeenCalledWith("review");
  });
});
