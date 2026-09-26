// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ConfirmedSecretInput, confirmedSecretProblem } from "./confirmed-secret-input";

describe("confirmedSecretProblem", () => {
  it("needs a required secret, and two equal entries", () => {
    expect(confirmedSecretProblem({ value: "", confirmation: "" })).toBeNull();
    expect(confirmedSecretProblem({ value: "", confirmation: "", isRequired: true })).toBe(
      "required"
    );
    expect(confirmedSecretProblem({ value: "sk-1", confirmation: "" })).toBe("mismatch");
    expect(confirmedSecretProblem({ value: "", confirmation: "sk-1" })).toBe("mismatch");
    expect(confirmedSecretProblem({ value: "sk-1", confirmation: "sk-2" })).toBe("mismatch");
    expect(confirmedSecretProblem({ value: "sk-1", confirmation: "sk-1" })).toBeNull();
  });
});

function Harness({
  showErrors = false,
  isRequired = true,
  valueError
}: {
  showErrors?: boolean;
  isRequired?: boolean;
  valueError?: string;
}) {
  const [value, setValue] = useState("");
  const [confirmation, setConfirmation] = useState("");
  return (
    <ConfirmedSecretInput
      label="API-nyckel"
      confirmLabel="Bekräfta API-nyckel"
      description="Krypteras före lagring."
      value={value}
      confirmation={confirmation}
      onValueChange={setValue}
      onConfirmationChange={setConfirmation}
      autoComplete="off"
      isRequired={isRequired}
      requiredMessage="Ange API-nyckeln."
      mismatchMessage="Nycklarna matchar inte. Skriv samma nyckel i båda fälten."
      showErrors={showErrors}
      valueError={valueError}
    />
  );
}

const key = () => screen.getByLabelText(/^API-nyckel/);
const confirmation = () => screen.getByLabelText(/^Bekräfta API-nyckel/);

describe("ConfirmedSecretInput", () => {
  it("is two labelled password fields that accept paste and password managers", async () => {
    const { container } = renderInApp(<Harness />);

    for (const input of [key(), confirmation()]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("off");
      expect(input.getAttribute("aria-required")).toBe("true");
      // Nothing cancels a paste.
      expect(fireEvent.paste(input)).toBe(true);
    }
    expect(key().getAttribute("aria-describedby")).toBeTruthy();
    expect(within(container).getByText("Krypteras före lagring.")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("waits until the confirmation is left before it says the entries differ", async () => {
    const { container } = renderInApp(<Harness />);
    // The field's own text; Astryx's live region repeats it for a while.
    const text = within(container);
    fireEvent.change(key(), { target: { value: "sk-live-1234" } });
    confirmation().focus();
    fireEvent.change(confirmation(), { target: { value: "sk-live" } });

    // Still typing: no error yet.
    expect(confirmation().getAttribute("aria-invalid")).toBeNull();
    expect(text.queryByText(/matchar inte/)).toBeNull();

    fireEvent.blur(confirmation());

    expect(confirmation().getAttribute("aria-invalid")).toBe("true");
    const error = text.getByText("Nycklarna matchar inte. Skriv samma nyckel i båda fälten.");
    expect(confirmation().getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(container);

    // Fixed: the error goes at once.
    fireEvent.change(confirmation(), { target: { value: "sk-live-1234" } });
    expect(confirmation().getAttribute("aria-invalid")).toBeNull();
    expect(text.queryByText(/matchar inte/)).toBeNull();
  });

  it("shows a missing required secret once the form was submitted", () => {
    const { container, rerender } = renderInApp(<Harness />);
    expect(within(container).queryByText("Ange API-nyckeln.")).toBeNull();

    rerender(<Harness showErrors />);

    expect(key().getAttribute("aria-invalid")).toBe("true");
    expect(within(container).getByText("Ange API-nyckeln.")).toBeTruthy();
    expect(confirmation().getAttribute("aria-invalid")).toBeNull();
  });

  it("shows what is wrong with the secret itself at the first field", async () => {
    const { container } = renderInApp(<Harness valueError="Använd minst 12 tecken" />);

    const error = within(container).getByText("Använd minst 12 tecken");
    expect(key().getAttribute("aria-invalid")).toBe("true");
    expect(key().getAttribute("aria-describedby")).toContain(error.id);
    expect(confirmation().getAttribute("aria-invalid")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("asks for the confirmation of an optional secret once one is typed", () => {
    renderInApp(<Harness isRequired={false} showErrors />);
    expect(key().getAttribute("aria-required")).toBeNull();
    expect(confirmation().getAttribute("aria-required")).toBeNull();

    fireEvent.change(key(), { target: { value: "token" } });

    expect(confirmation().getAttribute("aria-required")).toBe("true");
    // Submitted without the confirmation: a mismatch, at the confirmation.
    expect(confirmation().getAttribute("aria-invalid")).toBe("true");
  });
});
