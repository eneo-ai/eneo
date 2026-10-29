// @vitest-environment jsdom
import { StrictMode } from "react";
import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { navigateTo } from "@/lib/navigate-to";
import { getSessionSnapshot, handleRefusal } from "@/lib/api/refusal";
import { LogoutHandoff, logoutTarget } from "./logout-handoff";

vi.mock("@/lib/navigate-to", () => ({ navigateTo: vi.fn() }));
vi.mock("@/lib/api/refusal", () => ({
  SESSION_GENERATION_HEADER: "Eneo-Session-Generation",
  getSessionSnapshot: vi.fn(),
  handleRefusal: vi.fn()
}));
const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(getSessionSnapshot).mockReturnValue({ status: "bound", generation: "generation-a" });
});
afterEach(() => vi.unstubAllGlobals());

it.each([
  [{}, "/login?message=logout"],
  [{ reason: "expired", next: "/admin" }, "/login?message=expired"],
  [{ reason: "password_changed", next: "/admin" }, "/login?message=password_changed&next=%2Fadmin"],
  [{ reason: "password_changed", next: "https://evil.example" }, "/login?message=password_changed"]
])("keeps logout continuation within the app: %j", (search, target) => {
  expect(logoutTarget(search)).toBe(target);
});

it.each(["/login", "/login?message=logout"])(
  "posts once under StrictMode before replacing the document with %s",
  async (target) => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    renderInApp(
      <StrictMode>
        <LogoutHandoff target={target} />
      </StrictMode>
    );
    await waitFor(() =>
      expect(navigateTo).toHaveBeenCalledExactlyOnceWith(target, { replace: true })
    );
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/session/logout/", {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      headers: { "Eneo-Session-Generation": "generation-a" }
    });
    expect(handleRefusal).not.toHaveBeenCalled();
  }
);

it.each([403, 503, "network"])("keeps a failed logout visible (%s)", async (failure) => {
  if (failure === "network") fetchMock.mockRejectedValue(new TypeError("Offline"));
  else fetchMock.mockResolvedValue(new Response(null, { status: Number(failure) }));
  renderInApp(<LogoutHandoff target="/login" />);
  expect(await screen.findByText("Utloggningen misslyckades. Försök igen.")).toBeTruthy();
  expect(navigateTo).not.toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("link").getAttribute("href")).toBe("/logout");
});
