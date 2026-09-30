import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { parse } from "svelte/compiler";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

// SSR compilation removes onMount. Execute the page's actual instance script,
// retaining its callback logic while replacing only browser/framework boundaries.
const source = readFileSync(new URL("./+page.svelte", import.meta.url), "utf8");
const instance = parse(source, { modern: true }).instance;
if (instance === null) throw new Error("Callback page has no instance script");
const script = transpileModule(source.slice(instance.content.start, instance.content.end), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 }
}).outputText;

const CALLBACK_ORIGIN = "https://eneo.example";
const CALLBACK_QUERY = "?code=provider-code&state=bound-state&session_state=provider-session";
const SERVICE_ACCOUNT_STORAGE_KEY = "sharepoint_service_account_oauth";

function callbackBrowser(openerOrigin: string | null, storedState?: string) {
  const delivered: unknown[] = [];
  const postMessage = vi.fn((message: unknown, targetOrigin: string) => {
    // Model Window.postMessage's delivery boundary, including the unsafe wildcard.
    if (targetOrigin === "*" || targetOrigin === openerOrigin) delivered.push(message);
  });
  const close = vi.fn();
  const storage = new Map<string, string>();
  if (storedState !== undefined) {
    storage.set(SERVICE_ACCOUNT_STORAGE_KEY, JSON.stringify({ state: storedState }));
  }
  const sessionStorage = {
    getItem: vi.fn((key: string) => storage.get(key) ?? null),
    removeItem: vi.fn((key: string) => storage.delete(key))
  };

  const window = {
    location: new URL(`${CALLBACK_ORIGIN}/integrations/callback/token/${CALLBACK_QUERY}`),
    opener: openerOrigin === null ? null : { postMessage },
    close
  };

  return { delivered, postMessage, close, sessionStorage, window };
}

async function mountCallback(browser: ReturnType<typeof callbackBrowser>) {
  const lifecycle: { mounted?: () => Promise<void> } = {};
  runInNewContext(
    script,
    {
      exports: {},
      require: (name: string) => {
        if (name === "svelte") {
          return {
            onMount: (callback: () => Promise<void>) => {
              lifecycle.mounted = callback;
            }
          };
        }
        if (name === "$lib/paraglide/messages") {
          return {
            m: { integration_callback_oauth_state_mismatch: () => "OAuth state mismatch" }
          };
        }
        throw new Error(`Unexpected callback script import: ${name}`);
      },
      $state: (value: unknown) => value,
      window: browser.window,
      sessionStorage: browser.sessionStorage,
      URL,
      setTimeout
    },
    { timeout: 1000, filename: "integration-callback-page.js" }
  );
  const mounted = lifecycle.mounted;
  if (mounted === undefined) throw new Error("Callback page did not register its mount behavior");
  const completed = mounted();
  await vi.runAllTimersAsync();
  await completed;
}

describe("integration OAuth callback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test("delivers the provider callback to the Eneo popup opener", async () => {
    const browser = callbackBrowser(CALLBACK_ORIGIN);

    await mountCallback(browser);

    expect(browser.delivered).toEqual([
      {
        type: "eneo/integration-callback",
        code: "provider-code",
        state: "bound-state",
        params: CALLBACK_QUERY
      }
    ]);
    expect(browser.postMessage).toHaveBeenCalledWith(browser.delivered[0], CALLBACK_ORIGIN);
    expect(browser.close).toHaveBeenCalledOnce();
  });

  test.each([undefined, "bound-state"])(
    "never delivers OAuth credentials to a foreign opener with stored state %s",
    async (storedState) => {
      const browser = callbackBrowser("https://foreign.example", storedState);

      await mountCallback(browser);

      expect(browser.delivered).toEqual([]);
      expect(browser.postMessage).toHaveBeenCalledWith(
        {
          type: "eneo/integration-callback",
          code: "provider-code",
          state: "bound-state",
          params: CALLBACK_QUERY
        },
        CALLBACK_ORIGIN
      );
      expect(browser.sessionStorage.removeItem).not.toHaveBeenCalled();
    }
  );

  test("consumes a matching service-account state when there is no popup opener", async () => {
    const browser = callbackBrowser(null, "bound-state");

    await mountCallback(browser);

    expect(browser.postMessage).not.toHaveBeenCalled();
    expect(browser.sessionStorage.removeItem).toHaveBeenCalledWith(SERVICE_ACCOUNT_STORAGE_KEY);
    expect(browser.close).not.toHaveBeenCalled();
  });

  test("preserves a mismatched service-account state without sending the callback", async () => {
    const browser = callbackBrowser(null, "another-attempt");

    await mountCallback(browser);

    expect(browser.postMessage).not.toHaveBeenCalled();
    expect(browser.sessionStorage.removeItem).not.toHaveBeenCalled();
    expect(browser.close).not.toHaveBeenCalled();
  });
});
