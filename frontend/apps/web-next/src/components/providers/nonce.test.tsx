// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { NonceProvider, useNonce } from "./nonce";

afterEach(() => vi.unstubAllGlobals());

function Reader() {
  return <span>{useNonce()}</span>;
}

it("provides the nonce without overwriting or clearing boot state during StrictMode or unmount", () => {
  vi.stubGlobal("__webpack_nonce__", "boot-nonce");
  const view = render(
    <StrictMode>
      <NonceProvider nonce="context-nonce">
        <Reader />
      </NonceProvider>
    </StrictMode>
  );
  expect(screen.getByText("context-nonce")).toBeTruthy();
  expect(globalThis.__webpack_nonce__).toBe("boot-nonce");
  view.unmount();
  expect(globalThis.__webpack_nonce__).toBe("boot-nonce");
});
