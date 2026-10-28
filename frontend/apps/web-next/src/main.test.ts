// @vitest-environment jsdom
import { waitFor } from "@testing-library/dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.resetModules();
  document.documentElement.lang = "en";
  document.head.innerHTML = '<meta property="csp-nonce" nonce="boot-nonce">';
  document.body.innerHTML = '<div id="root"></div>';
});

afterEach(() => {
  vi.doUnmock("./boot");
  vi.doUnmock("./lib/runtime-config");
  vi.doUnmock("./render-app");
  vi.unstubAllGlobals();
  delete globalThis.__webpack_nonce__;
});

async function prepare() {
  const messages = deferred<Record<string, string>>();
  const config = deferred<object>();
  const loadMessages = vi.fn(() => messages.promise);
  const loadRuntimeConfig = vi.fn(() => config.promise);
  const setRuntimeConfig = vi.fn();
  const renderApp = vi.fn();
  const evaluated = vi.fn();
  vi.doMock("./boot", async () => ({
    ...(await vi.importActual<typeof import("./boot")>("./boot")),
    loadMessages
  }));
  vi.doMock("./lib/runtime-config", () => ({ loadRuntimeConfig, setRuntimeConfig }));
  vi.doMock("./render-app", async () => {
    const { config } = await import("zod");
    evaluated(globalThis.__webpack_nonce__, config().jitless);
    return { renderApp };
  });
  await import("./main");
  return {
    messages,
    config,
    loadMessages,
    loadRuntimeConfig,
    setRuntimeConfig,
    renderApp,
    evaluated
  };
}

it("loads catalogue and config concurrently, then evaluates UI with nonce and jitless Zod ready", async () => {
  const boot = await prepare();
  expect(boot.loadMessages).toHaveBeenCalledWith("en");
  expect(boot.loadRuntimeConfig).toHaveBeenCalledOnce();
  expect(boot.evaluated).not.toHaveBeenCalled();
  boot.messages.resolve({ greeting: "Hello" });
  await Promise.resolve();
  expect(boot.renderApp).not.toHaveBeenCalled();
  boot.config.resolve({ version: "test" });
  await waitFor(() => expect(boot.renderApp).toHaveBeenCalledOnce());
  expect(boot.setRuntimeConfig).toHaveBeenCalledWith({ version: "test" });
  expect(boot.evaluated).toHaveBeenCalledWith("boot-nonce", true);
  expect(boot.renderApp).toHaveBeenCalledWith(document.getElementById("root"), {
    locale: "en",
    messages: { greeting: "Hello" },
    nonce: "boot-nonce"
  });
});

it.each(["messages", "config"] as const)(
  "shows static recovery without loading React when %s fails",
  async (failed) => {
    const boot = await prepare();
    boot[failed].reject(new Error("Unavailable"));
    await waitFor(() => expect(document.querySelector('h1[lang="sv"]')).not.toBeNull());
    boot[failed === "messages" ? "config" : "messages"].resolve({});
    await Promise.resolve();
    expect(boot.evaluated).not.toHaveBeenCalled();
    expect(boot.renderApp).not.toHaveBeenCalled();
    expect(document.querySelector('p[lang="en"]')).not.toBeNull();
    expect(document.querySelector("a")?.getAttribute("href")).toBe("");
  }
);
