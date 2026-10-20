import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import { followServiceAccountSignIn, SignInAddressError } from "./service-account-sign-in";

vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn() } }));

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

describe("followServiceAccountSignIn", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubBrowser() {
    const assign = vi.fn();
    const setItem = vi.fn();
    vi.stubGlobal("window", { location: { assign } });
    vi.stubGlobal("sessionStorage", { setItem });
    return { assign, setItem };
  }

  it("keeps the state and leaves for an https sign-in page", () => {
    const { assign, setItem } = stubBrowser();
    followServiceAccountSignIn(
      { auth_url: "https://login.microsoftonline.com/a?x=1", state: "s" },
      t
    );
    expect(setItem).toHaveBeenCalledWith(
      "sharepoint_service_account_oauth",
      JSON.stringify({ state: "s" })
    );
    expect(assign).toHaveBeenCalledWith("https://login.microsoftonline.com/a?x=1");
  });

  it.each(["http://login.example.com/", "javascript:alert(1)", "/relative", ""])(
    "refuses %j",
    (auth_url) => {
      const { assign, setItem } = stubBrowser();
      expect(() => followServiceAccountSignIn({ auth_url, state: "s" }, t)).toThrow(
        new SignInAddressError(
          "Servern gav en inloggningsadress som inte är https. Kontakta din administratör."
        )
      );
      expect(assign).not.toHaveBeenCalled();
      expect(setItem).not.toHaveBeenCalled();
    }
  );
});
