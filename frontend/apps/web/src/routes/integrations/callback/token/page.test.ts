import { readInstanceScript, runInstanceScript } from "$lib/test/instanceScript";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

// Run the page's actual instance script; see $lib/test/instanceScript for why.
const script = readInstanceScript(new URL("./+page.svelte", import.meta.url));

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
  runInstanceScript(script, {
    filename: "integration-callback-page.js",
    modules: {
      svelte: {
        onMount: (callback: () => Promise<void>) => {
          lifecycle.mounted = callback;
        }
      },
      "$lib/paraglide/messages": {
        m: { integration_callback_oauth_state_mismatch: () => "OAuth state mismatch" }
      },
      // Used only in the markup today, so TypeScript elides them. Stubbed so
      // moving them into the script does not break this test unexpectedly.
      "$app/navigation": { goto: async () => undefined },
      "$app/forms": { enhance: () => undefined }
    },
    globals: {
      $state: (value: unknown) => value,
      window: browser.window,
      sessionStorage: browser.sessionStorage,
      URL,
      setTimeout
    }
  });
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
