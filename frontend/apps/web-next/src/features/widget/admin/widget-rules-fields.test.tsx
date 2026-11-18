// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSyncExternalStore } from "react";
import { renderInApp } from "@/test/render";
import { WidgetAutosave, type Widget } from "./autosave";
import { WidgetRulesFields } from "./widget-rules-fields";

// Astryx's NumberInput clamps what is typed to its range before it reports
// it; this stand-in reports the raw number, so the field's own out-of-range
// handling can be exercised.
vi.mock("@astryxdesign/core/NumberInput", () => ({
  NumberInput: ({
    label,
    value,
    onChange,
    status
  }: {
    label: string;
    value: number;
    onChange: (value: number | null) => void;
    status?: { message: string };
  }) => (
    <label>
      {label}
      <input
        type="number"
        value={value}
        aria-invalid={status ? true : undefined}
        onChange={(event) =>
          onChange(event.target.value === "" ? null : Number(event.target.value))
        }
      />
      {status && <span>{status.message}</span>}
    </label>
  )
}));

function widget(): Widget {
  return {
    id: "w1",
    name: "Kaffe",
    status: "draft",
    revision: 3,
    texts: { title: "Kaffehjälpen", welcome: "" },
    theme: { primary_color: "#1F4E79", radius: 12 },
    persona: {},
    limits: {
      daily_token_budget: 500000,
      messages_per_ip_hour: 60,
      max_question_chars: 1000,
      max_session_turns: 20
    },
    privacy: { retention_days: 30, store_feedback_text: false },
    allowed_origins: ["https://www.kommun.se"],
    bot_protection: "altcha",
    activation_blockers: [],
    template: null
  } as unknown as Widget;
}

/** The rules fields as the editor mounts them: state read from the store. */
function Rules({ autosave }: { autosave: WidgetAutosave }) {
  const state = useSyncExternalStore(
    autosave.subscribe,
    autosave.getSnapshot,
    autosave.getSnapshot
  );
  return <WidgetRulesFields autosave={autosave} state={state} policy={null} />;
}

afterEach(() => vi.restoreAllMocks());

describe("WidgetRulesFields", () => {
  it("holds an out-of-range number without re-rendering without end, and lets it go once corrected", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const save = vi.fn(async (update: Record<string, unknown>) => ({ ...widget(), ...update }));
    const autosave = new WidgetAutosave(widget(), save, { delay: 10 });
    renderInApp(<Rules autosave={autosave} />);

    const budget = screen.getByRole("spinbutton", { name: "Daglig tokenbudget" });
    fireEvent.change(budget, { target: { value: "5" } });
    expect(await screen.findByText(/Ange ett heltal mellan/)).toBeTruthy();
    expect(autosave.hasDrafts).toBe(true);
    expect(save).not.toHaveBeenCalled();

    fireEvent.change(budget, { target: { value: "2000" } });
    await waitFor(() => expect(screen.queryByText(/Ange ett heltal mellan/)).toBeNull());
    expect(autosave.hasDrafts).toBe(false);
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({ limits: expect.objectContaining({ daily_token_budget: 2000 }) })
      )
    );
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("Maximum update depth");
  });
});
