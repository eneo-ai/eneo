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
        aria-describedby="extra"
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
// only, over any the caller passes; the wrapper adds the caller's after them.
// When Astryx keeps the caller's ids, drop the wrapper, its lint rule and this
// test.
it("adds the caller's aria-describedby after Astryx's own description and status", () => {
  const { rerender } = renderInApp(<Field />);
  expect(describedBy()).toEqual(["Minst 12 tecken", "Kraven"]);

  // Astryx rewrites the attribute when the status appears.
  rerender(<Field error="Använd minst 12 tecken" />);
  expect(describedBy()).toEqual(["Minst 12 tecken", "Använd minst 12 tecken", "Kraven"]);

  rerender(<Field />);
  expect(describedBy()).toEqual(["Minst 12 tecken", "Kraven"]);
});
