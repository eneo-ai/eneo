// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { LoginFormState } from "./actions";

const action = vi.hoisted(() => ({
  result: { error: "invalid_credentials" } as LoginFormState,
  /** Holds the answer back until the test lets it through. */
  hold: null as Promise<void> | null
}));

// The server action (session cookies, backend call) is replaced by what it returns.
const loginAction = vi.hoisted(() =>
  vi.fn(async (_previous: LoginFormState, formData: FormData) => {
    await action.hold;
    return { ...action.result, email: String(formData.get("email") ?? "") };
  })
);
vi.mock("./actions", () => ({ loginAction }));

import { LoginForm } from "./login-form";

afterEach(() => {
  cleanup();
  loginAction.mockClear();
  action.hold = null;
});

function submit(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("E-post"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Lösenord"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Logga in" }));
}

describe("LoginForm", () => {
  it("works with password managers", () => {
    renderInApp(<LoginForm />);
    expect(screen.getByLabelText("E-post").getAttribute("autocomplete")).toBe("username");
    expect(screen.getByLabelText("Lösenord").getAttribute("autocomplete")).toBe("current-password");
  });

  it("keeps the e-mail address and moves focus to the error after a failed attempt", async () => {
    const { container } = renderInApp(<LoginForm />);
    submit("anna@kommun.se", "fel-lösenord");

    const error = await screen.findByRole("alert");
    expect(error.textContent).toBe("Ogiltiga inloggningsuppgifter");
    await waitFor(() => expect(document.activeElement).toBe(error));
    const email = screen.getByLabelText("E-post") as HTMLInputElement;
    expect(email.value).toBe("anna@kommun.se");
    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(email.getAttribute("aria-describedby")).toBe(error.id);
    await expectNoAxeViolations(container);
  });

  it("counts the attempts left after a wrong password", async () => {
    action.result = { error: "invalid_credentials", attemptsRemaining: 2, retryAfterSeconds: null };
    const { container } = renderInApp(<LoginForm />);
    submit("anna@kommun.se", "fel-lösenord");

    const error = await screen.findByRole("alert");
    expect(error.textContent).toBe(
      "Ogiltiga inloggningsuppgifterFörsök kvar innan inloggningen spärras tillfälligt: 2."
    );
    expect(screen.getByLabelText("E-post").getAttribute("aria-invalid")).toBe("true");
    await expectNoAxeViolations(container);
    action.result = { error: "invalid_credentials" };
  });

  it("says how long to wait when the last allowed attempt failed", async () => {
    action.result = { error: "invalid_credentials", attemptsRemaining: 0, retryAfterSeconds: 540 };
    renderInApp(<LoginForm />);
    submit("anna@kommun.se", "fel-lösenord");

    const error = await screen.findByRole("alert");
    expect(error.textContent).toBe(
      "För många misslyckade inloggningsförsök. Försök igen om 9 min."
    );
    action.result = { error: "invalid_credentials" };
  });

  it("says how long to wait when the backend refuses the attempt, without blaming the password", async () => {
    action.result = { error: "too_many_attempts", attemptsRemaining: 0, retryAfterSeconds: 30 };
    renderInApp(<LoginForm />);
    submit("anna@kommun.se", "rätt-lösenord");

    const error = await screen.findByRole("alert");
    // Never "0 min": the wait is rounded up to whole minutes.
    expect(error.textContent).toBe(
      "För många misslyckade inloggningsförsök. Försök igen om 1 min."
    );
    await waitFor(() => expect(document.activeElement).toBe(error));
    expect(screen.getByLabelText("E-post").hasAttribute("aria-invalid")).toBe(false);
    expect(screen.getByLabelText("Lösenord").hasAttribute("aria-invalid")).toBe(false);
    action.result = { error: "invalid_credentials" };
  });

  it("asks to try later when the backend refuses the attempt without saying for how long", async () => {
    action.result = {
      error: "too_many_attempts",
      attemptsRemaining: null,
      retryAfterSeconds: null
    };
    renderInApp(<LoginForm />);
    submit("anna@kommun.se", "rätt-lösenord");

    const error = await screen.findByRole("alert");
    expect(error.textContent).toBe("För många misslyckade inloggningsförsök. Försök igen senare.");
    action.result = { error: "invalid_credentials" };
  });

  it("does not mark the fields invalid when the service is unavailable", async () => {
    action.result = { error: "unavailable" };
    renderInApp(<LoginForm />);
    submit("anna@kommun.se", "rätt-lösenord");

    const error = await screen.findByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(error));
    expect(screen.getByLabelText("E-post").hasAttribute("aria-invalid")).toBe(false);
    action.result = { error: "invalid_credentials" };
  });

  it("keeps focus on a busy Logga in and signs in once", async () => {
    let release: () => void = () => {};
    action.hold = new Promise((resolve) => {
      release = resolve;
    });
    renderInApp(<LoginForm />);
    const login = screen.getByRole("button", { name: "Logga in" });
    login.focus();

    submit("anna@kommun.se", "rätt-lösenord");

    await waitFor(() => expect(login.getAttribute("aria-busy")).toBe("true"));
    expect(login.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(login);
    fireEvent.click(login);
    release();
    await screen.findByRole("alert");
    // A second submit would have queued a second sign-in behind the first.
    await act(async () => {});
    expect(loginAction).toHaveBeenCalledTimes(1);
  });
});
