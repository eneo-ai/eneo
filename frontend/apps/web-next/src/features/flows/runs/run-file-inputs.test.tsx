// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { makeInput } from "./run-fixtures";
import type { UploadEntry } from "./run-contract";
import { focusFirstControl } from "./run-form-fields";
import { inputFileAnchorId, RunFileInput } from "./run-file-inputs";

afterEach(cleanup);

/** Stands in for a recorder: what it holds, a recording running, must outlive a turn of the phone. */
function Recorder({ mounted }: { mounted: () => void }) {
  const [seconds, setSeconds] = useState(0);
  mounted();
  return (
    <button type="button" onClick={() => setSeconds((current) => current + 1)}>
      Spelar in {seconds}
    </button>
  );
}

function renderInput(mounted: () => void) {
  return renderInApp(
    <RunFileInput
      formId="form"
      input={makeInput({ input_format: "audio", accepted_mimetypes: ["audio/wav"] })}
      entries={[]}
      message={null}
      onAdd={() => {}}
      onRemove={() => {}}
      singleRecording={{ offered: false, value: false, onChange: () => {} }}
      recorder={<Recorder mounted={mounted} />}
    />
  );
}

describe("RunFileInput", () => {
  it("sends focus to the file field, not to the recorder above it, when the files are what is wrong", () => {
    setViewport("phone");
    renderInput(() => {});
    focusFirstControl(inputFileAnchorId("form", "step-1"));
    expect(document.activeElement?.closest("[id$='-files']")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Spelar in/ })).not.toBe(document.activeElement);
  });

  it("counts the files as the step's limit does, not the rows that failed", () => {
    const entry = { name: "brev.pdf", size: 1, mimetype: "application/pdf" };
    renderInApp(
      <RunFileInput
        formId="form"
        input={makeInput({ max_files: 2 })}
        entries={[
          { ...entry, key: "a", state: "done", progress: 1, fileId: "file-1" },
          { ...entry, key: "b", state: "uploading", progress: 0.5 },
          { ...entry, key: "c", state: "failed", progress: 0, problem: "För stor" }
        ]}
        message={null}
        onAdd={() => {}}
        onRemove={() => {}}
        singleRecording={{ offered: false, value: false, onChange: () => {} }}
      />
    );
    expect(screen.getByText("Filer: 2 av 2")).toBeTruthy();
  });

  it("counts the files only near the limit", () => {
    const entry = { name: "brev.pdf", size: 1, mimetype: "application/pdf" };
    renderInApp(
      <RunFileInput
        formId="form"
        input={makeInput({ max_files: 1000 })}
        entries={[{ ...entry, key: "a", state: "done", progress: 1, fileId: "file-1" }]}
        message={null}
        onAdd={() => {}}
        onRemove={() => {}}
        singleRecording={{ offered: false, value: false, onChange: () => {} }}
      />
    );
    expect(screen.queryByText(/^Filer:/)).toBeNull();
  });

  it("says a picked file is of the wrong type, in place of the form's earlier message", () => {
    const onAdd = vi.fn();
    const { container } = renderInApp(
      <RunFileInput
        formId="form"
        input={makeInput({ accepted_mimetypes: ["application/pdf"] })}
        entries={[]}
        message="Välj en fil för Underlag."
        onAdd={onAdd}
        onRemove={() => {}}
        singleRecording={{ offered: false, value: false, onChange: () => {} }}
      />
    );
    expect(screen.getByText("Välj en fil för Underlag.")).toBeTruthy();
    const picker = container.querySelector<HTMLInputElement>("input[type='file']")!;
    fireEvent.change(picker, {
      target: { files: [new File(["x"], "bild.png", { type: "image/png" })] }
    });
    expect(onAdd).not.toHaveBeenCalled();
    expect(screen.queryByText("Välj en fil för Underlag.")).toBeNull();
    expect(screen.getByText(/bild\.png/)).toBeTruthy();
  });

  it("keeps a recording running when a tablet is split down to a phone width", () => {
    const mounted = vi.fn();
    renderInput(mounted);
    fireEvent.click(screen.getByRole("button", { name: "Spelar in 0" }));
    fireEvent.click(screen.getByRole("button", { name: "Spelar in 1" }));

    // The recorder goes above the file field, and back.
    act(() => setViewport("phone"));
    expect(screen.getByRole("button", { name: "Spelar in 2" })).toBeTruthy();
    act(() => setViewport("tablet-portrait"));
    expect(screen.getByRole("button", { name: "Spelar in 2" })).toBeTruthy();
    act(() => setViewport("phone"));
    expect(screen.getByRole("button", { name: "Spelar in 2" })).toBeTruthy();
    // A phone turned sideways is still a phone: nothing moves.
    act(() => setViewport({ width: 844, height: 390, pointer: "coarse" }));
    expect(screen.getByRole("button", { name: "Spelar in 2" })).toBeTruthy();
  });

  it("keeps focus in the field when a file row is removed", async () => {
    const file = { name: "brev.pdf", size: 1, mimetype: "application/pdf", progress: 1 };
    function Field() {
      const [entries, setEntries] = useState<UploadEntry[]>([
        { ...file, key: "a", state: "done", fileId: "file-1" }
      ]);
      return (
        <RunFileInput
          formId="form"
          input={makeInput({ max_files: 3 })}
          entries={entries}
          message={null}
          onAdd={() => {}}
          onRemove={(key) => setEntries((current) => current.filter((entry) => entry.key !== key))}
          singleRecording={{ offered: false, value: false, onChange: () => {} }}
        />
      );
    }
    renderInApp(<Field />);
    const remove = screen.getByRole("button", { name: "Ta bort brev.pdf" });
    remove.focus();
    fireEvent.click(remove);
    await waitFor(() =>
      expect(document.activeElement?.closest("[id='form-input-step-1-files']")).toBeTruthy()
    );
  });
});
