// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { ChangePasswordCard } from "./change-password.client";

/** The backend's local policy, with two character classes switched on. */
const eneo = {
  source: "eneo" as const,
  policy: {
    min_length: 12,
    max_bytes: 72,
    requires_uppercase: true,
    requires_lowercase: false,
    requires_number: true,
    requires_symbol: false
  }
};

function renderCard(passwordChange: unknown = eneo) {
  return renderInApp(<ChangePasswordCard />, {
    appContext: testAppContext({ user: { password_change: passwordChange } as never })
  });
}

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement;
const type = (name: RegExp, value: string) => fireEvent.change(field(name), { target: { value } });
const save = () => fireEvent.submit(screen.getByRole("button", { name: "Spara" }).closest("form")!);
/** The field's error, read from the text its aria-describedby points at. */
const errorOf = (input: HTMLInputElement) =>
  input.getAttribute("aria-invalid") === "true"
    ? (input.getAttribute("aria-describedby") ?? "")
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent ?? "")
        .join(" ")
    : null;

const refused = (code: number) =>
  Promise.resolve({
    error: { message: "Refused", eneo_error_code: code },
    response: new Response(null, { status: 400 })
  });

afterEach(() => vi.clearAllMocks());

describe("ChangePasswordCard", () => {
  it("states the backend's policy before the field and gives password managers what they need", async () => {
    const { container } = renderCard();

    // The login form's `username` is the email.
    const account = container.querySelector<HTMLInputElement>('input[autocomplete="username"]');
    expect(account?.value).toBe("anna.lind@example.se");
    expect(account?.getAttribute("aria-hidden")).toBe("true");
    expect(account?.tabIndex).toBe(-1);
    expect(field(/^Nuvarande lösenord/).getAttribute("autocomplete")).toBe("current-password");
    for (const input of [field(/^Nytt lösenord/), field(/^Bekräfta lösenord/)]) {
      expect(input.getAttribute("autocomplete")).toBe("new-password");
    }
    // The policy's rules, not a length of its own (WCAG 3.3.2).
    const rules = within(container).getByText(
      "Använd minst 12 tecken. Inkludera en stor bokstav A–Z. Inkludera en siffra 0–9."
    );
    expect(field(/^Nytt lösenord/).getAttribute("aria-describedby")).toContain(rules.id);
    expect((screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement).disabled).toBe(
      false
    );
    await expectNoAxeViolations(container);
  });

  it("shows each problem at its field on submit and moves focus to the first", async () => {
    const { container } = renderCard();

    save();

    expect(errorOf(field(/^Nuvarande lösenord/))).toContain("Ange ditt nuvarande lösenord.");
    expect(errorOf(field(/^Nytt lösenord/))).toContain("Ange ett nytt lösenord.");
    expect(document.activeElement).toBe(field(/^Nuvarande lösenord/));
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(container);
  });

  it("checks the new password against the policy, and against the current one", () => {
    renderCard();
    type(/^Nuvarande lösenord/, "Gammalt-lösen1");

    for (const [password, error] of [
      ["Kort1A", "Använd minst 12 tecken"],
      ["langt-losenord-1", "Inkludera en stor bokstav A–Z"],
      ["Langt-losenord", "Inkludera en siffra 0–9"],
      ["Gammalt-lösen1", "Det nya lösenordet måste skilja sig från det nuvarande lösenordet."]
    ]) {
      type(/^Nytt lösenord/, password!);
      type(/^Bekräfta lösenord/, password!);
      save();
      expect(errorOf(field(/^Nytt lösenord/))).toContain(error);
      expect(document.activeElement).toBe(field(/^Nytt lösenord/));
    }
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("says at the confirmation when it is missing or differs", () => {
    renderCard();
    type(/^Nuvarande lösenord/, "Gammalt-lösen1");
    type(/^Nytt lösenord/, "Nytt-lösenord-2026");

    save();
    expect(errorOf(field(/^Bekräfta lösenord/))).toContain(
      "Skriv det nya lösenordet en gång till."
    );
    expect(document.activeElement).toBe(field(/^Bekräfta lösenord/));

    type(/^Bekräfta lösenord/, "Nytt-lösenord-2025");
    save();
    expect(errorOf(field(/^Bekräfta lösenord/))).toContain(
      "Lösenorden matchar inte. Skriv samma lösenord i båda fälten."
    );
  });

  it("sends a password that meets the policy", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderCard();
    type(/^Nuvarande lösenord/, "Gammalt-lösen1");
    type(/^Nytt lösenord/, "Nytt-lösenord-2026");
    type(/^Bekräfta lösenord/, "Nytt-lösenord-2026");

    save();

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/users/me/password/", {
        body: { current_password: "Gammalt-lösen1", new_password: "Nytt-lösenord-2026" }
      })
    );
  });

  it("shows what the backend refuses at the field it concerns", async () => {
    renderCard();
    type(/^Nuvarande lösenord/, "Fel-lösenord-1");
    type(/^Nytt lösenord/, "Nytt-lösenord-2026");
    type(/^Bekräfta lösenord/, "Nytt-lösenord-2026");

    api.POST.mockImplementation(() => refused(9061));
    save();
    await waitFor(() =>
      expect(errorOf(field(/^Nuvarande lösenord/))).toContain(
        "Det nuvarande lösenordet är felaktigt."
      )
    );
    expect(document.activeElement).toBe(field(/^Nuvarande lösenord/));
    expect(toast.error).not.toHaveBeenCalled();

    // Fixing it clears the refusal.
    type(/^Nuvarande lösenord/, "Gammalt-lösen1");
    expect(errorOf(field(/^Nuvarande lösenord/))).toBeNull();

    api.POST.mockImplementation(() => refused(9059));
    save();
    await waitFor(() =>
      expect(errorOf(field(/^Nytt lösenord/))).toContain(
        "Det nya lösenordet uppfyller inte den aktuella lösenordspolicyn."
      )
    );
    expect(document.activeElement).toBe(field(/^Nytt lösenord/));
  });

  it("leaves a password an identity provider manages to that provider", () => {
    renderCard({ source: "external", policy: null });

    expect(
      screen.getByText("Ditt lösenord hanteras av din identitetsleverantör och måste ändras där.")
    ).toBeTruthy();
    expect(screen.queryByLabelText(/^Nuvarande lösenord/)).toBeNull();
  });

  it("offers no form when the policy cannot be read", () => {
    renderCard({ source: "eneo" });

    expect(
      screen.getByText(
        "Vi kunde inte avgöra var ditt lösenord hanteras. Ladda om sidan och försök igen."
      )
    ).toBeTruthy();
    expect(screen.queryByLabelText(/^Nytt lösenord/)).toBeNull();
  });
});
