// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { IntlProvider } from "use-intl";
import { useState, type ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { SaveStatusIndicator, SaveStatusProvider } from "./save-status";
import { useAutosave, useAutosaveField, useDirtySaveStatus } from "./use-autosave";

const messages = {
  all_changes_saved: "All changes saved!",
  save_failed: "Couldn't save changes",
  saving: "Saving...",
  unsaved_changes: "{count, plural, one {# unsaved change} other {# unsaved changes}}"
};

afterEach(() => {
  cleanup();
  setVisibilityState("visible");
});

function withStatus(children: ReactNode) {
  return (
    <IntlProvider locale="en" messages={messages}>
      <SaveStatusProvider>
        {children}
        <SaveStatusIndicator />
      </SaveStatusProvider>
    </IntlProvider>
  );
}

function renderWithStatus(children: ReactNode) {
  return render(withStatus(children));
}

function DirtyProbe({ dirty }: { dirty: boolean }) {
  useDirtySaveStatus("dirty-field", dirty);
  return null;
}

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function AutosaveProbe({ saves }: { saves: Array<() => Promise<void>> }) {
  const autosave = useAutosave("queued-field");
  return (
    <button
      type="button"
      onClick={() => {
        for (const save of saves) void autosave(save);
      }}
    >
      Run
    </button>
  );
}

function AutosaveFieldProbe({ save }: { save: (value: string) => Promise<unknown> }) {
  const field = useAutosaveField({
    key: "text-field",
    value: "server",
    save,
    commitOnVisibilityChange: true
  });

  return (
    <input
      aria-label="Text field"
      value={field.value}
      onChange={(event) => field.setValue(event.target.value)}
    />
  );
}

function setVisibilityState(value: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value
  });
}

it("surfaces dirty drafts and guards unload", async () => {
  const { rerender } = renderWithStatus(<DirtyProbe dirty={false} />);

  expect(screen.getByText("All changes saved!")).toBeDefined();

  rerender(
    <IntlProvider locale="en" messages={messages}>
      <SaveStatusProvider>
        <DirtyProbe dirty />
        <SaveStatusIndicator />
      </SaveStatusProvider>
    </IntlProvider>
  );

  expect(screen.getByText("1 unsaved change")).toBeDefined();

  await waitFor(() => {
    const event = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(event)).toBe(false);
  });
});

it("keeps saving visible until every save for the key has settled", async () => {
  const first = deferred();
  const second = deferred();
  renderWithStatus(<AutosaveProbe saves={[() => first.promise, () => second.promise]} />);

  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  expect(screen.getByText("Saving...")).toBeDefined();

  await act(async () => first.resolve());
  expect(screen.getByText("Saving...")).toBeDefined();

  await act(async () => second.resolve());
  await waitFor(() => expect(screen.getByText("All changes saved!")).toBeDefined());
});

it("pops the check mark in when a save lands, and not before", async () => {
  const first = deferred();
  const { container } = renderWithStatus(<AutosaveProbe saves={[() => first.promise]} />);
  const check = () => container.querySelector("[data-success-mark]");

  // At rest on first render: a plain check, nothing animates.
  expect(check()?.getAttribute("class")).not.toContain("animate-in");

  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  expect(screen.getByText("Saving...")).toBeDefined();
  await act(async () => first.resolve());
  await waitFor(() => expect(screen.getByText("All changes saved!")).toBeDefined());

  // The landing animates (tw-animate-css enter utilities; the global
  // reduced-motion rule shortens them to nothing).
  expect(check()?.getAttribute("class")).toContain("animate-in");
});

it("commits a dirty autosave field when the document is hidden", async () => {
  const save = vi.fn(() => Promise.resolve());
  renderWithStatus(<AutosaveFieldProbe save={save} />);

  fireEvent.change(screen.getByRole("textbox", { name: "Text field" }), {
    target: { value: "draft" }
  });
  expect(screen.getByText("1 unsaved change")).toBeDefined();

  setVisibilityState("hidden");
  fireEvent(document, new Event("visibilitychange"));

  await waitFor(() => expect(save).toHaveBeenCalledWith("draft"));
  await waitFor(() => expect(screen.getByText("1 unsaved change")).toBeDefined());
});

function DebouncedFieldProbe({
  save,
  onSaved
}: {
  save: (value: string) => Promise<unknown>;
  onSaved?: (result: unknown) => void;
}) {
  const field = useAutosaveField({
    key: "debounced-field",
    value: "server",
    save,
    onSaved,
    commitDebounceMs: 100
  });

  return (
    <>
      <input
        aria-label="Text field"
        value={field.value}
        onChange={(event) => field.setValue(event.target.value)}
        onBlur={() => void field.commit()}
      />
      <button
        type="button"
        onClick={() => {
          field.setValue("applied");
          void field.commit("applied");
        }}
      >
        Apply
      </button>
    </>
  );
}

it("sends a blur commit once even when the save outlasts the debounce", async () => {
  vi.useFakeTimers();
  try {
    const pending = deferred();
    const save = vi.fn(() => pending.promise);
    renderWithStatus(<DebouncedFieldProbe save={save} />);
    const input = screen.getByRole("textbox", { name: "Text field" });

    fireEvent.change(input, { target: { value: "draft" } });
    act(() => vi.advanceTimersByTime(50));
    fireEvent.blur(input);
    expect(save).toHaveBeenCalledTimes(1);

    // The armed debounce and any later commit of the same in-flight value send nothing.
    act(() => vi.advanceTimersByTime(500));
    fireEvent.blur(input);
    expect(save).toHaveBeenCalledTimes(1);

    await act(async () => pending.resolve());
  } finally {
    vi.useRealTimers();
  }
});

it("commits a dirty draft when the field unmounts", async () => {
  const save = vi.fn(() => Promise.resolve());
  const { unmount } = renderWithStatus(<DebouncedFieldProbe save={save} />);

  fireEvent.change(screen.getByRole("textbox", { name: "Text field" }), {
    target: { value: "draft" }
  });
  unmount();

  expect(save).toHaveBeenCalledTimes(1);
  expect(save).toHaveBeenCalledWith("draft");
});

it("commits an explicit value before the draft state settles and reports the result", async () => {
  const save = vi.fn((value: string) => Promise.resolve({ saved: value }));
  const onSaved = vi.fn();
  renderWithStatus(<DebouncedFieldProbe save={save} onSaved={onSaved} />);

  fireEvent.click(screen.getByRole("button", { name: "Apply" }));

  expect(save).toHaveBeenCalledTimes(1);
  expect(save).toHaveBeenCalledWith("applied");
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ saved: "applied" }));
});

/** The server value is a prop, so a test decides when a landed save renders. */
function ServerBackedProbe({
  server,
  save,
  commitDebounceMs
}: {
  server: string;
  save: (value: string) => Promise<void>;
  commitDebounceMs?: number;
}) {
  const field = useAutosaveField({
    key: "server-backed-field",
    value: server,
    save,
    commitDebounceMs
  });

  return (
    <>
      <output aria-label="Draft">{field.value}</output>
      <input
        aria-label="Text field"
        value={field.value}
        onChange={(event) => field.setValue(event.target.value)}
      />
      {["A", "B"].map((value) => (
        <button
          key={value}
          type="button"
          onClick={() => {
            field.setValue(value);
            void field.commit(value);
          }}
        >
          Pick {value}
        </button>
      ))}
      <button type="button" onClick={() => void field.commit()}>
        Retry
      </button>
    </>
  );
}

function deferredSaves() {
  const saves: Array<{ value: string; done: ReturnType<typeof deferred> }> = [];
  const save = vi.fn((value: string) => {
    const done = deferred();
    saves.push({ value, done });
    return done.promise;
  });
  return { saves, save };
}

const draftText = () => screen.getByRole("status", { name: "Draft" }).textContent;

it("keeps a reverted choice made while the previous save is still pending", async () => {
  const { saves, save } = deferredSaves();
  const { rerender } = renderWithStatus(<ServerBackedProbe server="A" save={save} />);

  fireEvent.click(screen.getByRole("button", { name: "Pick B" }));
  fireEvent.click(screen.getByRole("button", { name: "Pick A" }));
  expect(saves.map((entry) => entry.value)).toEqual(["B", "A"]);

  await act(async () => saves[0]?.done.resolve());
  rerender(withStatus(<ServerBackedProbe server="B" save={save} />));
  expect(draftText()).toBe("A");
  await act(async () => saves[1]?.done.resolve());
  rerender(withStatus(<ServerBackedProbe server="A" save={save} />));
  expect(draftText()).toBe("A");
});

function RemovableField({ save }: { save: (value: string) => Promise<unknown> }) {
  const [shown, setShown] = useState(true);
  return (
    <>
      {shown && <DebouncedFieldProbe save={save} />}
      <button type="button" onClick={() => setShown(false)}>
        Remove field
      </button>
    </>
  );
}

it("keeps reporting a pending save after its field unmounts", async () => {
  const pending = deferred();
  const save = vi.fn(() => pending.promise);
  renderWithStatus(<RemovableField save={save} />);
  const input = screen.getByRole("textbox", { name: "Text field" });

  fireEvent.change(input, { target: { value: "draft" } });
  fireEvent.blur(input);
  fireEvent.click(screen.getByRole("button", { name: "Remove field" }));

  expect(save).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Saving...")).toBeDefined();
  await act(async () => pending.resolve());
  await waitFor(() => expect(screen.getByText("All changes saved!")).toBeDefined());
});

function NormalizedFieldProbe({ save }: { save: (value: string) => Promise<unknown> }) {
  const field = useAutosaveField({
    key: "normalized-field",
    value: " Existing name ",
    normalize: (value: string) => value.trim(),
    save
  });
  return <output>{field.value}</output>;
}

it("does not write an untouched field on unmount, even when normalizing would change it", () => {
  const save = vi.fn(() => Promise.resolve());
  const { unmount } = renderWithStatus(<NormalizedFieldProbe save={save} />);

  unmount();

  expect(save).not.toHaveBeenCalled();
});

it("keeps a reverted choice whose save failed, and retries it", async () => {
  const { saves, save } = deferredSaves();
  const { rerender } = renderWithStatus(<ServerBackedProbe server="A" save={save} />);

  fireEvent.click(screen.getByRole("button", { name: "Pick B" }));
  fireEvent.click(screen.getByRole("button", { name: "Pick A" }));
  // B lands and A fails before the landed B renders.
  await act(async () => {
    saves[0]?.done.resolve();
    saves[1]?.done.reject(new Error("refused"));
  });
  rerender(withStatus(<ServerBackedProbe server="B" save={save} />));

  expect(draftText()).toBe("A");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(saves.map((entry) => entry.value)).toEqual(["B", "A", "A"]);
});

it("adopts a later server change after a revert whose saves both landed unrendered", async () => {
  const { saves, save } = deferredSaves();
  const { rerender } = renderWithStatus(<ServerBackedProbe server="A" save={save} />);

  fireEvent.click(screen.getByRole("button", { name: "Pick B" }));
  fireEvent.click(screen.getByRole("button", { name: "Pick A" }));
  await act(async () => {
    saves[0]?.done.resolve();
    saves[1]?.done.resolve();
  });
  rerender(withStatus(<ServerBackedProbe server="C" save={save} />));

  expect(draftText()).toBe("C");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(save).toHaveBeenCalledTimes(2);
});

it("debounces a revert typed while the previous value is in flight, and keeps it", async () => {
  vi.useFakeTimers();
  try {
    const { saves, save } = deferredSaves();
    const { rerender } = renderWithStatus(
      <ServerBackedProbe server="A" save={save} commitDebounceMs={100} />
    );
    const input = screen.getByRole("textbox", { name: "Text field" });

    fireEvent.change(input, { target: { value: "B" } });
    act(() => vi.advanceTimersByTime(100));
    fireEvent.change(input, { target: { value: "A" } });
    act(() => vi.advanceTimersByTime(100));
    expect(saves.map((entry) => entry.value)).toEqual(["B", "A"]);

    await act(async () => saves[0]?.done.resolve());
    rerender(withStatus(<ServerBackedProbe server="B" save={save} commitDebounceMs={100} />));
    expect(draftText()).toBe("A");
  } finally {
    vi.useRealTimers();
  }
});

it("adopts another editor's change after a revert whose saves both failed", async () => {
  const { saves, save } = deferredSaves();
  const { rerender } = renderWithStatus(<ServerBackedProbe server="A" save={save} />);

  fireEvent.click(screen.getByRole("button", { name: "Pick B" }));
  fireEvent.click(screen.getByRole("button", { name: "Pick A" }));
  await act(async () => {
    saves[0]?.done.reject(new Error("refused"));
    saves[1]?.done.reject(new Error("refused"));
  });
  rerender(withStatus(<ServerBackedProbe server="C" save={save} />));

  expect(draftText()).toBe("C");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(save).toHaveBeenCalledTimes(2);
});

it("adopts the server's form of a landed save, so a later change by another editor is not overwritten", async () => {
  const { saves, save } = deferredSaves();
  const { rerender, unmount } = renderWithStatus(<ServerBackedProbe server="30" save={save} />);
  const input = screen.getByRole("textbox", { name: "Text field" });

  fireEvent.change(input, { target: { value: "07" } });
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await act(async () => saves[0]?.done.resolve());
  // The server stores 7 and returns it in its own form.
  rerender(withStatus(<ServerBackedProbe server="7" save={save} />));
  expect(draftText()).toBe("7");

  rerender(withStatus(<ServerBackedProbe server="3" save={save} />));
  expect(draftText()).toBe("3");
  unmount();
  expect(save).toHaveBeenCalledTimes(1);
});

it("sends a revert whose debounce ends after the earlier save landed but before it renders", async () => {
  vi.useFakeTimers();
  try {
    const { saves, save } = deferredSaves();
    const { rerender } = renderWithStatus(
      <ServerBackedProbe server="A" save={save} commitDebounceMs={100} />
    );
    const input = screen.getByRole("textbox", { name: "Text field" });

    fireEvent.change(input, { target: { value: "B" } });
    act(() => vi.advanceTimersByTime(100));
    fireEvent.change(input, { target: { value: "A" } });
    await act(async () => saves[0]?.done.resolve());
    act(() => vi.advanceTimersByTime(100));
    expect(saves.map((entry) => entry.value)).toEqual(["B", "A"]);

    rerender(withStatus(<ServerBackedProbe server="B" save={save} commitDebounceMs={100} />));
    expect(draftText()).toBe("A");
  } finally {
    vi.useRealTimers();
  }
});

it("does not retry a failed debounced save on its own", async () => {
  vi.useFakeTimers();
  try {
    const save = vi.fn(() => Promise.reject(new Error("refused")));
    renderWithStatus(<ServerBackedProbe server="A" save={save} commitDebounceMs={100} />);

    fireEvent.change(screen.getByRole("textbox", { name: "Text field" }), {
      target: { value: "B" }
    });
    await act(async () => vi.advanceTimersByTime(100));
    await act(async () => vi.advanceTimersByTime(5000));

    expect(save).toHaveBeenCalledTimes(1);
    expect(draftText()).toBe("B");
  } finally {
    vi.useRealTimers();
  }
});
