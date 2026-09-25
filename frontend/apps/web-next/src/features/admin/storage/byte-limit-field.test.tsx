// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { ByteLimitField } from "./byte-limit-field";

function Field() {
  const [bytes, setBytes] = useState(1024);
  return (
    <>
      <ByteLimitField
        id="limit"
        label="Limit"
        description="Help"
        bytes={bytes}
        storedBytes={1024}
        disabled={false}
        onChange={setBytes}
      />
      <output data-testid="bytes">{String(bytes)}</output>
    </>
  );
}

afterEach(cleanup);

describe("storage byte limit field", () => {
  it("preserves bytes when changing units and leaves an empty edit invalid", () => {
    render(<Field />);
    const amount = screen.getByRole("spinbutton") as HTMLInputElement;
    const unit = screen.getByRole("combobox") as HTMLSelectElement;
    expect(amount.value).toBe("1");
    expect(unit.value).toBe("KB");
    fireEvent.change(unit, { target: { value: "B" } });
    expect(amount.value).toBe("1024");
    fireEvent.change(amount, { target: { value: "" } });
    expect(amount.value).toBe("");
    expect(amount.getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(amount, { target: { value: "2048" } });
    expect(screen.getByTestId("bytes").textContent).toBe("2048");
  });
});
