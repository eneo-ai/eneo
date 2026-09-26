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
