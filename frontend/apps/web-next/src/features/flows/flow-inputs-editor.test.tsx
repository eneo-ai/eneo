// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { flowFixture } from "./flow-fixtures";
import { FlowInputsEditor, stepsReadingInput } from "./flow-inputs-editor";
import type { FormField } from "./types";

afterEach(cleanup);

const definition = flowFixture.definition;

describe("stepsReadingInput", () => {
  it("names the steps that read an input by template, as a file, or for speaker names", () => {
    expect(stepsReadingInput("recording", definition).map((step) => step.key)).toEqual([
      "transcript",
      "summary"
    ]);
    expect(stepsReadingInput("participants", definition).map((step) => step.key)).toEqual([
      "transcript"
    ]);
  });
});

describe("FlowInputsEditor", () => {
  it("adds an input with a key from its label, blocks removing one a step reads, and saves the list", async () => {
    const onSave = vi.fn<(fields: FormField[]) => Promise<void>>(() => Promise.resolve());
    const onOpenChange = vi.fn();
    renderInApp(
      <FlowInputsEditor
        definition={definition}
        open
        onOpenChange={onOpenChange}
        onSave={onSave}
        saving={false}
      />
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort Inspelning" }));
    expect(
      within(dialog).getByText(
        "Inspelning läses av Transkribera mötet, Sammanfatta beslut. Ändra de stegen först."
      )
    ).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till indata" }));
    fireEvent.change(within(dialog).getByLabelText(/Etikett/), {
      target: { value: "Diarienummer" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till" }));
    expect(within(dialog).getByText("Diarienummer")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Spara som utkast" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const fields = onSave.mock.calls[0]![0];
    expect(fields.at(-1)).toMatchObject({
      key: "diarienummer",
      label: "Diarienummer",
      type: "text",
      required: true
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });
});
