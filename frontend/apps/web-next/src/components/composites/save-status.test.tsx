// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
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

function renderWithStatus(children: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SaveStatusProvider>
        {children}
        <SaveStatusIndicator />
      </SaveStatusProvider>
    </NextIntlClientProvider>
  );
}

function DirtyProbe({ dirty }: { dirty: boolean }) {
  useDirtySaveStatus("dirty-field", dirty);
  return null;
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
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
    <NextIntlClientProvider locale="en" messages={messages}>
      <SaveStatusProvider>
        <DirtyProbe dirty />
        <SaveStatusIndicator />
      </SaveStatusProvider>
    </NextIntlClientProvider>
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
