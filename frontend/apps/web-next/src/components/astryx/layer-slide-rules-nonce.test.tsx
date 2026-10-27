// @vitest-environment jsdom
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { afterEach, expect, it } from "vitest";
import { renderInApp } from "@/test/render";

afterEach(() => {
  document.head.replaceChildren();
  globalThis.__webpack_nonce__ = undefined;
});

/** The nonced element the root layout serves in <head>. */
function serveNonce(nonce: string) {
  const served = document.createElement("style");
  served.setAttribute("nonce", nonce);
  document.head.append(served);
}

function renderLayer() {
  renderInApp(
    <Tooltip content="Mer information">
      <button type="button">Info</button>
    </Tooltip>
  );
  return document.getElementById("astryx-layer-slide-rules") as HTMLStyleElement | null;
}

// Guards frontend/patches/@astryxdesign%2Fcore@0.7.3.patch. Astryx installs
// its layers' `@position-try` slide rules as a <style> in <head>; without the
// request nonce the production CSP blocks it, and a menu or popover near the
// viewport edge can no longer slide or flip. The first layer can mount before
// NonceProvider sets `__webpack_nonce__` (its layout effect runs after its
// children's), so the patch reads the nonce the document was served with.
it("gives the layer slide rules the page's CSP nonce", () => {
  serveNonce("request-nonce");

  const rules = renderLayer();

  expect(rules?.textContent).toContain("@position-try");
  expect(rules?.nonce).toBe("request-nonce");
});

// A layer in another document (an iframe) needs that document's nonce, not
// the global of the window running the code.
it("prefers the layer document's nonce over the global one", () => {
  serveNonce("request-nonce");
  globalThis.__webpack_nonce__ = "other-document-nonce";

  expect(renderLayer()?.nonce).toBe("request-nonce");
});
