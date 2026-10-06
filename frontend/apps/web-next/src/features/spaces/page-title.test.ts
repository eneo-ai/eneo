import { redirect } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string, values?: Record<string, string>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));

import { spaceLayoutTitle, spacePageTitle } from "./page-title";

describe("spacePageTitle", () => {
  it("titles the page after the resource", async () => {
    await expect(spacePageTitle(async () => "Upphandlingspolicy", "collections")).resolves.toEqual({
      title: "Upphandlingspolicy"
    });
    await expect(
      spacePageTitle(async (t) => t("space_edit_title", { name: "Avtal" }), "assistants")
    ).resolves.toEqual({ title: 'space_edit_title:{"name":"Avtal"}' });
  });

  it("falls back to the tab's name when the resource cannot be loaded", async () => {
    const missing = new EneoApiError("Not found", { status: 404 });
    await expect(spacePageTitle(() => Promise.reject(missing), "collections")).resolves.toEqual({
      title: "collections"
    });
  });

  it("lets a redirect (an expired session) through", async () => {
    await expect(
      spacePageTitle(async () => redirect("/logout?reason=expired"), "apps")
    ).rejects.toMatchObject({ digest: expect.stringContaining("NEXT_REDIRECT") });
  });
});

describe("spaceLayoutTitle", () => {
  const space = { name: "Upphandling", personal: false, organization: false };

  it("names the tab after the space, with the template for the pages below", async () => {
    await expect(spaceLayoutTitle(async () => space)).resolves.toEqual({
      title: { default: "Upphandling", template: "%s · Upphandling · Eneo" }
    });
    await expect(
      spaceLayoutTitle(async () => ({ ...space, personal: true }))
    ).resolves.toMatchObject({ title: { default: "personal" } });
  });

  it("keeps the root title when the space cannot be loaded", async () => {
    const missing = new EneoApiError("Not found", { status: 404 });
    await expect(spaceLayoutTitle(() => Promise.reject(missing))).resolves.toEqual({});
  });

  it("lets a redirect (an expired session) through", async () => {
    await expect(
      spaceLayoutTitle(async () => redirect("/logout?reason=expired"))
    ).rejects.toMatchObject({ digest: expect.stringContaining("NEXT_REDIRECT") });
  });
});
