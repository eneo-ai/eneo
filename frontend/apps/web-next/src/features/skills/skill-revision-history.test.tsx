// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNameToHoldVisibleText } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SkillRevisionHistory } from "./skill-revision-history";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));

const revision: Schema<"SkillRevisionPublic"> = {
  id: "revision-1",
  skill_id: "skill-1",
  revision_number: 1,
  display_name: "Reports",
  description: "Report search",
  instructions: "Search carefully",
  content_digest: "fixture",
  created_by_user_id: "user-1",
  created_at: "2026-09-01T12:00:00Z"
};

it("names each revision's preview button by what it shows, then its version (WCAG 2.5.3)", async () => {
  get.mockResolvedValue({
    data: { items: [revision], next_cursor: null },
    response: new Response()
  });
  const skill = {
    id: "skill-1",
    current_revision_id: revision.id,
    current_revision: revision
  } as Schema<"SkillPublic">;
  renderInApp(
    <SkillRevisionHistory skill={skill} unsaved={false} scope={{ type: "organization" }} />
  );
  const name = "Förhandsvisning av version 1";
  expectNameToHoldVisibleText(await screen.findByRole("button", { name }), name);
});
