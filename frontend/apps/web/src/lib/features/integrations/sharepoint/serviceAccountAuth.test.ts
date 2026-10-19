import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import {
  SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY,
  followServiceAccountSignIn
} from "./serviceAccountAuth";

describe("followServiceAccountSignIn", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubBrowser() {
    const assign = vi.fn();
    const setItem = vi.fn();
    // The messages read the locale from the address too.
    vi.stubGlobal("window", {
      location: { assign, href: "http://localhost/", origin: "http://localhost" }
    });
    vi.stubGlobal("sessionStorage", { setItem });
    return { assign, setItem };
  }

  it("keeps the state and leaves for an https sign-in page", () => {
    const { assign, setItem } = stubBrowser();
    followServiceAccountSignIn({ auth_url: "https://login.microsoftonline.com/a?x=1", state: "s" });
    expect(setItem).toHaveBeenCalledWith(
      SHAREPOINT_SERVICE_ACCOUNT_OAUTH_KEY,
      JSON.stringify({ state: "s" })
    );
    expect(assign).toHaveBeenCalledWith("https://login.microsoftonline.com/a?x=1");
  });

  it.each(["http://login.example.com/", "javascript:alert(1)", "/relative", ""])(
    "refuses %j",
    (auth_url) => {
      const { assign, setItem } = stubBrowser();
      expect(() => followServiceAccountSignIn({ auth_url, state: "s" })).toThrow(
        m.sharepoint_sign_in_url_invalid()
      );
      expect(assign).not.toHaveBeenCalled();
      expect(setItem).not.toHaveBeenCalled();
    }
  );
});
