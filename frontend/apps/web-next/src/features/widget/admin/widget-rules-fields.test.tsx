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
    status,
    isDisabled
  }: {
    label: string;
    value: number;
    onChange: (value: number | null) => void;
    status?: { message: string };
    isDisabled?: boolean;
  }) => (
    <label>
      {label}
      <input
        type="number"
        value={value}
        aria-invalid={status ? true : undefined}
        aria-disabled={isDisabled ? true : undefined}
        readOnly={isDisabled}
        onChange={(event) =>
          onChange(event.target.value === "" ? null : Number(event.target.value))
        }
      />
      {status && <span>{status.message}</span>}
    </label>
  )
}));

function widget(overrides: Partial<Widget> = {}): Widget {
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
    template: null,
    ...overrides
  } as unknown as Widget;
}

/** The rules fields as the editor mounts them: state read from the store. */
function Rules({ autosave, isAdmin }: { autosave: WidgetAutosave; isAdmin?: boolean }) {
  const state = useSyncExternalStore(
    autosave.subscribe,
    autosave.getSnapshot,
    autosave.getSnapshot
  );
  return <WidgetRulesFields autosave={autosave} state={state} policy={null} isAdmin={isAdmin} />;
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

const GOVERNED =
  "Tillåtna webbplatser, integritet och botskydd granskades av en organisationsadministratör vid aktiveringen. Medan widgeten är aktiv ändrar bara en administratör dem; pausa widgeten för att ändra dem själv.";

/** The fields an admin reviewed at activation, then a limit outside that review. */
function governedFields() {
  return {
    origins: screen.getByRole("textbox", { name: "Tillåtna webbplatser" }),
    retention: screen.getByRole("spinbutton", { name: "Lagringstid i dagar" }),
    feedback: screen.getByRole("switch", { name: /^Spara fritextåterkoppling/ }),
    protection: screen.getByRole("combobox", { name: /^Botskydd/ }),
    budget: screen.getByRole("spinbutton", { name: "Daglig tokenbudget" })
  };
}

describe("WidgetRulesFields governed settings", () => {
  it("an editor cannot change what an admin reviewed while the widget is active", async () => {
    const save = vi.fn(async (update: Record<string, unknown>) => ({ ...widget(), ...update }));
    const autosave = new WidgetAutosave(widget({ status: "active" }), save, { delay: 10 });
    renderInApp(<Rules autosave={autosave} isAdmin={false} />);

    expect(screen.getByRole("note").textContent).toBe(GOVERNED);
    const { origins, retention, feedback, protection, budget } = governedFields();
    for (const field of [origins, retention, feedback, protection]) {
      expect(field.getAttribute("aria-disabled")).toBe("true");
    }
    // The budget is capped by the policy at run time and stays the editor's.
    expect(budget.getAttribute("aria-disabled")).toBeNull();

    fireEvent.click(feedback);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(save).not.toHaveBeenCalled();
  });

  it.each([
    { case: "an admin on an active widget", status: "active", isAdmin: true },
    { case: "an editor on a draft", status: "draft", isAdmin: false }
  ] as const)("$case edits every rule", ({ status, isAdmin }) => {
    const autosave = new WidgetAutosave(widget({ status }), vi.fn(), { delay: 10 });
    renderInApp(<Rules autosave={autosave} isAdmin={isAdmin} />);
    expect(screen.queryByRole("note")).toBeNull();
    for (const field of Object.values(governedFields())) {
      expect(field.getAttribute("aria-disabled")).toBeNull();
    }
  });
});

describe("WidgetRulesFields allowed websites", () => {
  it("explains a saved wildcard the API no longer accepts, and holds no edit until it changes", async () => {
    const save = vi.fn(async (update: Record<string, unknown>) => ({ ...widget(), ...update }));
    const autosave = new WidgetAutosave(
      widget({
        allowed_origins: ["https://*.se"],
        activation_blockers: ["allowed_origin_too_broad"]
      }),
      save,
      { delay: 10 }
    );
    renderInApp(<Rules autosave={autosave} />);

    const origins = screen.getByRole("textbox", { name: "Tillåtna webbplatser" });
    expect(origins.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(/täcker en hel toppdomän/)).toBeTruthy();
    // Nothing was typed, so leaving the page has nothing to ask about.
    expect(autosave.hasDrafts).toBe(false);

    fireEvent.change(origins, { target: { value: "https://*.kommun.se" } });
    fireEvent.blur(origins);
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({ allowed_origins: ["https://*.kommun.se"] })
      )
    );
  });

  it("a saved list left, or typed back, as it was is explained as the saved one", () => {
    const autosave = new WidgetAutosave(
      widget({
        allowed_origins: ["https://*.se"],
        activation_blockers: ["allowed_origin_too_broad"]
      }),
      vi.fn(),
      { delay: 10 }
    );
    renderInApp(<Rules autosave={autosave} />);
    const origins = screen.getByRole("textbox", { name: "Tillåtna webbplatser" });
    const tooBroad = /täcker en hel toppdomän/;

    fireEvent.focus(origins);
    fireEvent.blur(origins);
    expect(screen.getByText(tooBroad)).toBeTruthy();

    fireEvent.change(origins, { target: { value: "https://*.se\nkontakt" } });
    fireEvent.blur(origins);
    expect(screen.getByText(/Ingen giltig origin/)).toBeTruthy();

    fireEvent.change(origins, { target: { value: "https://*.se" } });
    fireEvent.blur(origins);
    expect(screen.getByText(tooBroad)).toBeTruthy();
    expect(screen.queryByText(/Ingen giltig origin/)).toBeNull();
  });
});
