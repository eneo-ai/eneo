// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
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
