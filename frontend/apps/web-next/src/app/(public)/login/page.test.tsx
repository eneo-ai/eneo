import { Children, isValidElement, type ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { ContinueSignedIn } from "./continue-signed-in";
import LoginPage from "./page";

const { getSession, redirect } = vi.hoisted(() => ({
  getSession: vi.fn(),
  redirect: vi.fn(() => {
    throw new Error("NEXT_REDIRECT");
  })
}));
vi.mock("@/lib/auth/session", () => ({ getSession }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("next-intl/server", () => ({ getTranslations: async () => (key: string) => key }));

beforeEach(() => {
  vi.clearAllMocks();
  getSession.mockResolvedValue({ mode: "password" });
});

/** Where the signed-in login page continues to. */
async function continuesTo(next?: string) {
  const page = (await LoginPage({ searchParams: Promise.resolve({ next }) })) as ReactElement<{
    children: React.ReactNode;
  }>;
  const handOff = Children.toArray(page.props.children).find(
    (child): child is ReactElement<{ href: string }> =>
      isValidElement(child) && child.type === ContinueSignedIn
  );
  return handOff?.props.href;
}

// Signed in by the login action (its re-render) or already: a new document,
// never redirect(), which navigates client-side from an action or a soft visit.
it("continues a signed-in visitor to the next page in a new document", async () => {
  expect(await continuesTo("/spaces/abc?tab=files")).toBe("/spaces/abc?tab=files");
  expect(redirect).not.toHaveBeenCalled();
});

it("continues to the landing page when the next page is missing or not this app's", async () => {
  expect(await continuesTo()).toBe(DEFAULT_LANDING);
  expect(await continuesTo("//evil.example/spaces")).toBe(DEFAULT_LANDING);
});
