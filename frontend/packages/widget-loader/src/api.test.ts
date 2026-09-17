import { afterEach, describe, expect, it, vi } from "vitest";
import { installApi, type EneoApi } from "./api";
import { EneoWidgetElement } from "./element";

type EneoWindow = Window & { Eneo?: EneoApi };

if (!customElements.get("eneo-widget")) customElements.define("eneo-widget", EneoWidgetElement);

afterEach(() => {
  document.body.innerHTML = "";
  delete (window as EneoWindow).Eneo;
});

function mount(): EneoWidgetElement {
  const element = document.createElement("eneo-widget") as EneoWidgetElement;
  element.setAttribute("widget-id", "wgt_api");
  document.body.appendChild(element);
  return element;
}

describe("window.Eneo", () => {
  it("replays commands queued before the script loaded, once an element exists", () => {
    // The snippet hosts paste uses `arguments`; mirror it exactly.
    const stub = function () {
      // eslint-disable-next-line prefer-rest-params
      (stub.q = stub.q || []).push(arguments);
    } as unknown as EneoApi;
    (window as EneoWindow).Eneo = stub;
    const onOpen = vi.fn();
    stub("on", "open", onOpen);
    stub("open");

    const api = installApi(window as EneoWindow, "1.0.0");
    expect((window as EneoWindow).Eneo).toBe(api);
    expect(api.version).toBe("1.0.0");
    expect(onOpen).not.toHaveBeenCalled();

    const element = mount();
    expect(element.open).toBe(true);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("exposes method-style calls and unsubscribes listeners", () => {
    const api = installApi(window as EneoWindow, "1.0.0");
    const element = mount();
    const onClose = vi.fn();
    const off = api.on("close", onClose);

    api.open();
    expect(element.open).toBe(true);
    api.toggle();
    expect(element.open).toBe(false);
    expect(onClose).toHaveBeenCalledTimes(1);

    off();
    api("open");
    api("close");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("forwards page context to the element", () => {
    const api = installApi(window as EneoWindow, "1.0.0");
    const element = mount();
    const setContext = vi.spyOn(element, "setContext");
    api("setContext", { page_url: "https://host.example/a" });
    expect(setContext).toHaveBeenCalledWith({ page_url: "https://host.example/a" });
  });

  it("is installed once even if the script is included twice", () => {
    const first = installApi(window as EneoWindow, "1.0.0");
    const second = installApi(window as EneoWindow, "1.0.1");
    expect(second).toBe(first);
    expect(first.version).toBe("1.0.0");
  });

  it("ignores unknown events", () => {
    const api = installApi(window as EneoWindow, "1.0.0");
    expect(() => api.on("bogus" as never, vi.fn())).not.toThrow();
  });
});
