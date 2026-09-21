import { afterEach, describe, expect, it } from "vitest";
import { mountFromScript, resolveOrigin } from "./bootstrap";
import { EneoWidgetElement } from "./element";

if (!customElements.get("eneo-widget")) customElements.define("eneo-widget", EneoWidgetElement);

afterEach(() => {
  document.body.innerHTML = "";
});

function scriptTag(attributes: Record<string, string>): HTMLScriptElement {
  const script = document.createElement("script");
  for (const [name, value] of Object.entries(attributes)) script.setAttribute(name, value);
  return script;
}

describe("resolveOrigin", () => {
  it("uses the script origin and falls back to the page", () => {
    expect(
      resolveOrigin(scriptTag({ src: "https://eneo.example.se/widget/v1/eneo.js" }), "x")
    ).toBe("https://eneo.example.se");
    expect(resolveOrigin(scriptTag({}), "https://fallback.example")).toBe(
      "https://fallback.example"
    );
    expect(resolveOrigin(null, "https://fallback.example")).toBe("https://fallback.example");
  });
});

describe("mountFromScript", () => {
  it("mounts one element from the script's data attributes", () => {
    const script = scriptTag({
      "data-widget-id": "wgt_boot",
      "data-lang": "en",
      "data-position": "bottom-left",
      "data-color-scheme": "dark",
      "data-launcher": "none"
    });
    mountFromScript(script);
    mountFromScript(script);

    const elements = document.querySelectorAll("eneo-widget");
    expect(elements).toHaveLength(1);
    const element = elements[0] as EneoWidgetElement;
    expect(element.getAttribute("widget-id")).toBe("wgt_boot");
    expect(element.lang).toBe("en");
    expect(element.getAttribute("position")).toBe("bottom-left");
    expect(element.colorScheme).toBe("dark");
    expect(element.getAttribute("launcher")).toBe("none");
  });

  it("mounts a pinned bottom-left install snippet on the left", () => {
    const script = scriptTag({
      src: "https://eneo.kommun.se/widget/1.4.2/eneo.js",
      integrity: "sha384-abc",
      crossorigin: "anonymous",
      "data-widget-id": "wgt_left",
      "data-position": "bottom-left"
    });
    mountFromScript(script);
    const element = document.querySelector("eneo-widget") as EneoWidgetElement;
    expect(element.getAttribute("widget-id")).toBe("wgt_left");
    expect(element.getAttribute("position")).toBe("bottom-left");
  });

  it("does nothing without a widget id", () => {
    mountFromScript(scriptTag({ src: "https://eneo.example.se/widget/v1/eneo.js" }));
    expect(document.querySelector("eneo-widget")).toBeNull();
  });

  it("prefetches the iframe when asked", () => {
    mountFromScript(scriptTag({ "data-widget-id": "wgt_pre", "data-prefetch": "true" }));
    const element = document.querySelector("eneo-widget") as EneoWidgetElement;
    expect(element.shadowRoot!.querySelector("iframe")).not.toBeNull();
    expect(element.open).toBe(false);
  });
});
