// @vitest-environment jsdom
import { Switch } from "@astryxdesign/core/Switch";
import { TextInput } from "@astryxdesign/core/TextInput";
import { screen, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";

it("keeps the caller's description with the field's own description and error", () => {
  renderInApp(
    <>
      <p id="password-policy">Kraven</p>
      <TextInput
        label="Nytt lösenord"
        description="Minst 12 tecken"
        aria-describedby="password-policy"
        value="kort"
        onChange={() => {}}
        status={{ type: "error", message: "Använd minst 12 tecken" }}
      />
    </>
  );
  const field = screen.getByRole("textbox", { name: /^Nytt lösenord/ });
  const descriptions = field.getAttribute("aria-describedby")?.split(" ") ?? [];
  expect(descriptions.map((id) => document.getElementById(id)?.textContent)).toEqual(
    expect.arrayContaining(["Kraven", "Minst 12 tecken", "Använd minst 12 tecken"])
  );
  expect(field.getAttribute("aria-invalid")).toBe("true");
});

it("announces a busy switch in the app's Swedish locale", async () => {
  renderInApp(<Switch label="Aktiv" value={false} onChange={() => {}} isLoading />);
  expect(screen.getByRole("switch", { name: "Aktiv" }).getAttribute("aria-busy")).toBe("true");
  await waitFor(() =>
    expect(document.querySelector('[data-astryx-live-region="polite"]')?.textContent).toBe(
      "Läser in"
    )
  );
});
