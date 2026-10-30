// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { OutboundHeadersEditor } from "./outbound-headers-editor";
import {
  newHeaderRow,
  rowsFromHeaders,
  type HeaderRow,
  type OutboundHeaderOptions
} from "./outbound-headers";
import { useFieldFocus } from "./provider-form-fields";

const options: OutboundHeaderOptions = {
  dynamic_values: [
    {
      token: "user.employeeNumber",
      source: "scim_enterprise",
      attribute: "employeeNumber",
      classification: "identifying"
    }
  ],
  supported_provider_types: ["hosted_vllm"],
  max_headers: 2
};
function Editor({ initial = [], type = "hosted_vllm" }: { initial?: HeaderRow[]; type?: string }) {
  const [rows, setRows] = useState(initial);
  const focus = useFieldFocus();
  return (
    <OutboundHeadersEditor
      providerType={type}
      options={options}
      rows={rows}
      onChange={setRows}
      optionsError={false}
      loading={false}
      onRetry={() => {}}
      endpoint="http://gateway.internal"
      focus={focus}
    />
  );
}

describe("outbound header editor", () => {
  it("adds a focused row, inserts a server-defined token and explains identity and transport risks", async () => {
    renderInApp(<Editor />);
    fireEvent.click(screen.getByRole("button", { name: "Lägg till header" }));
    const row = screen.getByRole("group", { name: "Header 1" });
    const name = within(row).getByLabelText(/^Headernamn/);
    expect(document.activeElement).toBe(name);
    fireEvent.change(name, { target: { value: "X-Employee" } });
    fireEvent.click(within(row).getByRole("button", { name: /Infoga dynamiskt värde/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /user.employeeNumber/ }));
    expect((within(row).getByLabelText(/^Värde/) as HTMLInputElement).value).toBe(
      "{{user.employeeNumber}}"
    );
    expect(screen.getByText(/identifierar en enskild användare/)).toBeTruthy();
    expect(screen.getByText(/skickas okrypterade/)).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("preserves focus after deleting and explains the server-owned maximum", async () => {
    renderInApp(<Editor initial={[{ ...newHeaderRow(), name: "X-One", value: "one" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Lägg till header" }));
    const add = screen.getByRole("button", { name: "Lägg till header" });
    expect(add.hasAttribute("disabled") || add.getAttribute("aria-disabled") === "true").toBe(true);
    expect(screen.getByText("Du kan lägga till högst 2 headers.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ta bort headern Header 2" }));
    expect(document.activeElement).toBe(screen.getByLabelText(/^Headernamn/));
    fireEvent.click(screen.getByRole("button", { name: "Ta bort headern X-One" }));
    expect(document.activeElement).toBe(add);
    await expectNoAxeViolations(document.body);
  });

  it("changes and restores a stored secret without ever filling the mask into inputs", async () => {
    renderInApp(
      <Editor
        initial={rowsFromHeaders([
          {
            id: "h",
            name: "X-Credential",
            value: "********",
            secret: true,
            encoding: "none",
            on_missing: "fallback",
            fallback: "********"
          }
        ])}
      />
    );
    const change = screen.getByRole("button", { name: "Ändra värdet för X-Credential" });
    fireEvent.click(change);
    const value = screen.getByLabelText(/^Värde/) as HTMLInputElement;
    expect(document.activeElement).toBe(value);
    expect(value.value).toBe("");
    expect(value.type).toBe("password");
    fireEvent.change(value, { target: { value: "replacement" } });
    fireEvent.click(screen.getByRole("button", { name: "Avbryt och behåll det nuvarande värdet" }));
    expect(screen.queryByLabelText(/^Värde/)).not.toBeInstanceOf(HTMLInputElement);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Ändra värdet för X-Credential" })
    );
    expect(
      [...document.querySelectorAll("input")].some((input) => input.value === "********")
    ).toBe(false);
    await expectNoAxeViolations(document.body);
  });

  it("hides the editor for unsupported provider types", () => {
    renderInApp(<Editor type="openai" />);
    expect(screen.queryByRole("group", { name: "Utgående headers" })).toBeNull();
  });
});
