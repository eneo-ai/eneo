// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { ByteLimitField } from "./byte-limit-field";

function Field({ problem = null }: { problem?: string | null }) {
  const [bytes, setBytes] = useState(1024);
  return (
    <>
      <ByteLimitField
        id="limit"
        label="Limit"
        description="Help"
        bytes={bytes}
        storedBytes={1024}
        problem={problem}
        disabled={false}
        onChange={setBytes}
      />
      <output data-testid="bytes">{String(bytes)}</output>
    </>
  );
}

afterEach(cleanup);

describe("storage byte limit field", () => {
  it("preserves bytes when changing units and keeps an empty edit", () => {
    render(<Field />);
    const amount = screen.getByRole("spinbutton") as HTMLInputElement;
    const unit = screen.getByRole("combobox") as HTMLSelectElement;
    expect(amount.value).toBe("1");
    expect(unit.value).toBe("KB");
    fireEvent.change(unit, { target: { value: "B" } });
    expect(amount.value).toBe("1024");
    fireEvent.change(amount, { target: { value: "" } });
    expect(amount.value).toBe("");
    // Nothing is flagged while typing: the form shows problems on save.
    expect(amount.getAttribute("aria-invalid")).toBeNull();
    fireEvent.change(amount, { target: { value: "2048" } });
    expect(screen.getByTestId("bytes").textContent).toBe("2048");
  });

  it("shows its problem at the amount, before the help", () => {
    render(<Field problem="Ange ett positivt värde, till exempel 10 MB." />);
    const amount = screen.getByRole("spinbutton");

    expect(amount.getAttribute("aria-invalid")).toBe("true");
    expect(
      (amount.getAttribute("aria-describedby") ?? "")
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent)
    ).toEqual(["Ange ett positivt värde, till exempel 10 MB.", "Help"]);
  });
});
