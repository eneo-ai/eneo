// @vitest-environment jsdom
import { act, cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useTranslations } from "use-intl";
import { afterEach, expect, it, vi } from "vitest";
import { AppIntlProvider } from "@/components/providers/intl-provider";
import { toastApiError } from "@/lib/api/toast";
import { router } from "@/test/navigation";
import * as catalogs from "./locales";
import sv from "./messages/sv.json";
import { useLocaleSwitch } from "./use-locale-switch";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/toast", () => ({ toastApiError: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  document.cookie = "NEXT_LOCALE=; Max-Age=0; Path=/";
});

function Picker() {
  const { locale, switchLocale } = useLocaleSwitch();
  const t = useTranslations();
  return (
    <>
      <output>{locale}</output>
      <p>{t("loading")}</p>
      <button onClick={() => switchLocale("en")}>English</button>
    </>
  );
}

it("keeps the current catalogue and cookie when the selected catalogue fails to load", async () => {
  let fail!: (error: Error) => void;
  vi.spyOn(catalogs, "loadMessages").mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        fail = reject;
      })
  );
  document.cookie = "NEXT_LOCALE=sv; Path=/";
  render(
    <AppIntlProvider locale="sv" messages={sv}>
      <Picker />
    </AppIntlProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("en"));
  expect(document.cookie).toContain("NEXT_LOCALE=sv");
  expect(screen.getByText(sv.loading)).toBeTruthy();
  await act(async () => fail(new Error("catalogue unavailable")));
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("sv"));
  expect(document.cookie).toContain("NEXT_LOCALE=sv");
  expect(document.documentElement.lang).toBe("sv");
  expect(router.refresh).not.toHaveBeenCalled();
  expect(toastApiError).toHaveBeenCalledOnce();
});
