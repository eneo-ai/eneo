// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ConfirmedPasswordField, isConfirmedPasswordValid } from "./confirmed-password-field";

it("validates optional and required confirmed values", () => {
  expect(isConfirmedPasswordValid({ value: "", confirmation: "" })).toBe(true);
  expect(isConfirmedPasswordValid({ value: "", confirmation: "", required: true })).toBe(false);
  expect(isConfirmedPasswordValid({ value: "secret", confirmation: "" })).toBe(false);
  expect(isConfirmedPasswordValid({ value: "secret", confirmation: "wrong" })).toBe(false);
  expect(isConfirmedPasswordValid({ value: "secret", confirmation: "secret" })).toBe(true);
});

it("marks the confirmation field invalid when values do not match", () => {
  render(
    <ConfirmedPasswordField
      label="Password"
      confirmLabel="Confirm password"
      value="secret"
      confirmation="wrong"
      onValueChange={vi.fn()}
      onConfirmationChange={vi.fn()}
      errorMessage="Passwords do not match"
    />
  );

  expect(screen.getByText("Passwords do not match")).toBeDefined();
  expect(screen.getByLabelText(/Confirm password/).getAttribute("aria-invalid")).toBe("true");
});
