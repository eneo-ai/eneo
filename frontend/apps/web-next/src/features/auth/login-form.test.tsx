// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { submitPasswordLogin } from "./password-login";
import { LoginForm } from "./login-form";

vi.mock("./password-login", () => ({ submitPasswordLogin: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

it("submits credentials and next, preserves email and focuses a rejected attempt", async () => {
  vi.mocked(submitPasswordLogin).mockResolvedValue({
    error: "invalid_credentials",
    attemptsRemaining: 2
  });
  renderInApp(<LoginForm next="/admin" />);
  fireEvent.change(screen.getByLabelText(/^E-post/), { target: { value: "person@example.test" } });
  fireEvent.change(screen.getByLabelText(/^Lösenord/), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Logga in" }));
  await waitFor(() => expect(submitPasswordLogin).toHaveBeenCalledOnce());
  const [next, , body] = vi.mocked(submitPasswordLogin).mock.calls[0]!;
  expect(next).toBe("/admin");
  expect(body.get("email")).toBe("person@example.test");
  expect(body.get("password")).toBe("secret");
  expect((screen.getByLabelText(/^E-post/) as HTMLInputElement).value).toBe("person@example.test");
  await waitFor(() => expect(document.activeElement?.textContent).toMatch(/2/));
  const description = screen.getByLabelText(/^Lösenord/).getAttribute("aria-describedby")!;
  expect(
    description
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .join(" ")
  ).toMatch(/2/);
});

it("says sign-in is unavailable when the credentials were never checked", async () => {
  vi.mocked(submitPasswordLogin).mockResolvedValue({ error: "unavailable" });
  renderInApp(<LoginForm />);
  fireEvent.change(screen.getByLabelText(/^E-post/), { target: { value: "person@example.test" } });
  fireEvent.change(screen.getByLabelText(/^Lösenord/), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Logga in" }));
  expect(await screen.findByText(messages.login_unavailable)).toBeTruthy();
});

it("reveals a password without submitting the form", async () => {
  renderInApp(<LoginForm />);
  const field = screen.getByLabelText(/^Lösenord/);
  expect(field.getAttribute("type")).toBe("password");
  fireEvent.click(screen.getByRole("button", { name: "Visa lösenord" }));
  expect(field.getAttribute("type")).toBe("text");
  fireEvent.click(screen.getByRole("button", { name: "Dölj lösenord" }));
  expect(field.getAttribute("type")).toBe("password");
  expect(submitPasswordLogin).not.toHaveBeenCalled();
});

// WCAG 3.3.8 and 1.3.5: a password manager must be able to fill the form, and nothing
// may stop a pasted value (no paste blocking, no memory test, no transcribing a code).
it("names the fields for a password manager and does not block pasting", () => {
  renderInApp(<LoginForm />);
  const email = screen.getByLabelText(/^E-post/) as HTMLInputElement;
  const password = screen.getByLabelText(/^Lösenord/) as HTMLInputElement;
  expect(email.getAttribute("autocomplete")).toBe("username");
  expect(password.getAttribute("autocomplete")).toBe("current-password");

  const paste = (field: HTMLElement) => {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    field.dispatchEvent(event);
    return event.defaultPrevented;
  };
  expect(paste(email)).toBe(false);
  expect(paste(password)).toBe(false);
});
