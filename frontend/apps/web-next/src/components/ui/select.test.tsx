// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { NonceProvider } from "@/components/providers/nonce";
import { renderInApp } from "@/test/render";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";

it("gives every <style> it injects the request's CSP nonce", async () => {
  // Production allows a <style> only with the nonce (src/proxy.ts). An open
  // Select injects two: Radix's viewport scrollbar rule and the page scroll
  // lock (react-remove-scroll).
  renderInApp(
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

  const styles = [...document.querySelectorAll("style")];
  expect(styles.length - before).toBe(2);
  expect(styles.map((style) => style.getAttribute("nonce"))).toEqual(
    styles.map(() => "test-nonce")
  );
});
