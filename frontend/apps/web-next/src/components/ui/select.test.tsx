// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { NonceProvider } from "@/components/providers/nonce";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";

it("gives the styles injected by an open Select the request nonce", async () => {
  // Radix focuses the selected item; jsdom has no scrolling layout.
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: () => {}
  });
  render(
    <NonceProvider nonce="test-nonce">
      <Select defaultValue="sv">
        <SelectTrigger aria-label="Språk">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="sv">Svenska</SelectItem>
          <SelectItem value="en">English</SelectItem>
        </SelectContent>
      </Select>
    </NonceProvider>
  );
  const before = document.querySelectorAll("style").length;

  fireEvent.keyDown(screen.getByRole("combobox", { name: "Språk" }), { key: "Enter" });
  await screen.findByRole("listbox");

  const injected = [...document.querySelectorAll("style")].slice(before);
  expect(injected).toHaveLength(2);
  expect(injected.every((style) => style.getAttribute("nonce") === "test-nonce")).toBe(true);
});
