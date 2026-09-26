// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { LoginFormState } from "./actions";

const action = vi.hoisted(() => ({
  result: { error: "invalid_credentials" } as LoginFormState
}));

// The server action (session cookies, backend call) is replaced by what it returns.
vi.mock("./actions", () => ({
  loginAction: vi.fn(async (_previous: LoginFormState, formData: FormData) => ({
    ...action.result,
    email: String(formData.get("email") ?? "")
  }))
}));

import { LoginForm } from "./login-form";

afterEach(cleanup);

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
});
