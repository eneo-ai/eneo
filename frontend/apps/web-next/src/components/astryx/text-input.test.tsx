// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { TextInput } from "./text-input";

function Field({ error }: { error?: string }) {
  return (
    <>
      <p id="extra">Kraven</p>
      <TextInput
        label="Nytt lösenord"
        description="Minst 12 tecken"
        value=""
        onChange={() => {}}
        describedBy="extra"
        status={error ? { type: "error", message: error } : undefined}
      />
    </>
  );
}

const describedBy = () =>
  (screen.getByLabelText(/^Nytt lösenord/).getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent);

// Astryx 0.6.3 sets aria-describedby from its own description and status
// only, over any the caller passes; the wrapper adds `describedBy` after them.
// When Astryx lets callers add ids, drop the wrapper and this test.
it("adds describedBy after Astryx's own description and status, and keeps it", () => {
  const { rerender } = renderInApp(<Field />);
  expect(describedBy()).toEqual(["Minst 12 tecken", "Kraven"]);

  // Astryx rewrites the attribute when the status appears.
  rerender(<Field error="Använd minst 12 tecken" />);
  expect(describedBy()).toEqual(["Minst 12 tecken", "Använd minst 12 tecken", "Kraven"]);

  rerender(<Field />);
  expect(describedBy()).toEqual(["Minst 12 tecken", "Kraven"]);
});
