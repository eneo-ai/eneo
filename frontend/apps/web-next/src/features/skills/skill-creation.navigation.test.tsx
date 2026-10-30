// @vitest-environment jsdom
import { createRoute } from "@tanstack/react-router";
import { act, fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Link from "@/lib/link.tanstack";
import { renderWithRouter } from "@/test/router";
import { replaceInstructionText } from "@/test/skill-instructions";
import { OrganizationSkillNewPage } from "./organization-skill-new-page";
import { SpaceSkillNewPage } from "./space-skill-new-page";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: post } }));
vi.mock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
vi.mock("@/lib/link", () => import("@/lib/link.tanstack"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ space: { id: "space-1" }, routeId: "space-1" })
}));

it.each([
  { scope: "space-1", component: SpaceSkillNewPage },
  { scope: "organization", component: OrganizationSkillNewPage }
])(
  "opens a saved new Skill in $scope without asking to discard it",
  async ({ scope, component }) => {
    post.mockResolvedValue({ data: { id: "skill-1" }, response: new Response() });
    const base = `/spaces/${scope}/skills`;
    await renderWithRouter(null, {
      route: `${base}/new`,
      routes: (root) => [
        createRoute({ getParentRoute: () => root, path: `${base}/new`, component }),
        createRoute({
          getParentRoute: () => root,
          path: `${base}/skill-1`,
          component: () => <h1>Saved Skill</h1>
        })
      ]
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), {
      target: { value: "Reports" }
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
      target: { value: "Find reports" }
    });
    await act(async () =>
      replaceInstructionText(screen.getByLabelText("Instruktioner"), "Search the archive")
    );
    fireEvent.click(screen.getByRole("button", { name: "Skapa Skill" }));
    await screen.findByRole("heading", { name: "Saved Skill" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
  }
);

it.each([
  { scope: "space-1", component: SpaceSkillNewPage },
  { scope: "organization", component: OrganizationSkillNewPage }
])(
  "does not pull the user back after leaving a pending creation in $scope",
  async ({ scope, component }) => {
    let finish!: (reply: { data: { id: string }; response: Response }) => void;
    post.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const base = `/spaces/${scope}/skills`;
    const { router } = await renderWithRouter(<Link href="/left">Leave editor</Link>, {
      route: `${base}/new`,
      routes: (root) => [
        createRoute({ getParentRoute: () => root, path: `${base}/new`, component }),
        createRoute({
          getParentRoute: () => root,
          path: `${base}/skill-1`,
          component: () => <h1>Saved Skill</h1>
        }),
        createRoute({
          getParentRoute: () => root,
          path: "/left",
          component: () => <h1>Left editor</h1>
        })
      ]
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), {
      target: { value: "Reports" }
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
      target: { value: "Find reports" }
    });
    await act(async () =>
      replaceInstructionText(screen.getByLabelText("Instruktioner"), "Search the archive")
    );
    fireEvent.click(screen.getByRole("button", { name: "Skapa Skill" }));
    fireEvent.click(screen.getByRole("link", { name: "Leave editor" }));
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: "Lämna utan att spara" }));
    await screen.findByRole("heading", { name: "Left editor" });
    await act(async () => finish({ data: { id: "skill-1" }, response: new Response() }));
    expect(router.state.location.pathname).toBe("/left");
  }
);
