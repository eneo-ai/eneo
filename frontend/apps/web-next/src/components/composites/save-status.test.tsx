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
