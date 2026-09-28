// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp, testAppContext } from "@/test/render";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";
import { makeSpace } from "../testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: "space-1",
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const data = path.includes("ai-models")
        ? { completion_models: [], embedding_models: [], transcription_models: [] }
        : path.includes("security-classifications")
          ? { security_enabled: false, security_classifications: [] }
          : { items: [], total_count: 0, next_cursor: null };
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { SpaceSettings } from "./space-settings";

afterEach(cleanup);

function show(space: Space) {
  state.space = space;
  return renderInApp(<SpaceSettings />, { appContext: testAppContext({ permissions: ["admin"] }) });
}

describe("SpaceSettings", () => {
  it("offers section links and keeps each model type separate from tools", () => {
    show(makeSpace());

    const navigation = screen.getByRole("navigation", { name: "På den här sidan" });
    for (const name of [
      "Allmänt",
      "Säkerhet & Integritet",
      "Modeller",
      "Verktyg och anslutningar",
      "Funktioner",
      "API-nycklar",
      "Farozon"
    ]) {
      const link = within(navigation).getByRole("link", { name });
      const id = link.getAttribute("href")?.slice(1);
      expect(id).toBeTruthy();
      expect(document.getElementById(id!)).toBeTruthy();
    }
    const models = document.getElementById("models")!;
    expect(within(models).getByRole("heading", { name: "Chattmodeller" })).toBeTruthy();
    expect(within(models).getByRole("heading", { name: "Inbäddningsmodeller" })).toBeTruthy();
    expect(within(models).getByRole("heading", { name: "Transkriptionsmodeller" })).toBeTruthy();
    expect(within(models).queryByText("MCP-servrar")).toBeNull();
    expect(
      within(document.getElementById("tools")!).getAllByText("MCP-servrar").length
    ).toBeGreaterThan(0);
  });

  it("shows organization settings without personal space sections", () => {
    show(makeSpace({ overrides: { organization: true } }));

    const navigation = screen.getByRole("navigation", { name: "På den här sidan" });
    expect(within(navigation).queryByRole("link", { name: "Allmänt" })).toBeNull();
    expect(within(navigation).queryByRole("link", { name: "Säkerhet & Integritet" })).toBeNull();
    expect(within(navigation).queryByRole("link", { name: "Funktioner" })).toBeNull();
    expect(within(navigation).queryByRole("link", { name: "Farozon" })).toBeNull();
    expect(within(navigation).getByRole("link", { name: "Modeller" })).toBeTruthy();
    expect(within(navigation).getByRole("link", { name: "Verktyg och anslutningar" })).toBeTruthy();
  });
});
