import { describe, expect, it } from "vitest";
import { spaceHasPermission, type ResourcePermission, type SpaceResource } from "../space";
import { makeCollection, makeSpace, makeWebsite } from "../testing/space-fixture";
import {
  ownKnowledgeCount,
  spaceLandingHref,
  spaceNameIsPageHeading,
  spaceRoute,
  spaceSections
} from "./space-sections";

const canFor =
  (space: ReturnType<typeof makeSpace>) => (action: ResourcePermission, resource: SpaceResource) =>
    spaceHasPermission(space, action, resource);

describe("spaceSections", () => {
  it("lists every tab of a shared space with the counts the space carries", () => {
    const space = makeSpace({
      assistants: [{ id: "a1" }, { id: "a2" }],
      groupChats: [{ id: "g1" }],
      apps: [{ id: "p1" }],
      collections: [makeCollection(), makeCollection({ id: "shared", space_id: "other" })],
      websites: [makeWebsite()],
      members: [{ id: "u1" }, { id: "u2" }]
    });
    const sections = spaceSections(space, canFor(space), "space-1");

    expect(sections.map((section) => section.id)).toEqual([
      "overview",
      "assistants",
      "apps",
      "knowledge",
      "skills",
      "services",
      "members",
      "settings"
    ]);
    expect(Object.fromEntries(sections.map((section) => [section.id, section.count]))).toEqual({
      overview: undefined,
      assistants: 3,
      apps: 1,
      // The collection shared in from another space is not this space's knowledge.
      knowledge: 2,
      skills: undefined,
      services: undefined,
      members: 2,
      settings: undefined
    });
    expect(sections[3]?.href).toBe("/spaces/space-1/knowledge");
  });

  it("keeps the personal space without members and settings, as its permissions say", () => {
    const space = makeSpace({
      permissions: ["read"],
      overrides: {
        personal: true,
        members: { items: [], count: 0, permissions: [] }
      }
    });
    const ids = spaceSections(space, canFor(space), "personal").map((section) => section.id);
    expect(ids).toEqual(["overview", "assistants", "apps", "knowledge", "skills", "services"]);
  });

  it("limits the organization space to knowledge, skills, services and settings", () => {
    const space = makeSpace({ overrides: { organization: true } });
    const ids = spaceSections(space, canFor(space), "organization").map((section) => section.id);
    expect(ids).toEqual(["knowledge", "skills", "services", "settings"]);
    expect(
      spaceLandingHref(spaceSections(space, canFor(space), "organization"), "organization")
    ).toBe("/spaces/organization/knowledge");
  });

  it("hides tabs the user may not read", () => {
    const space = makeSpace({
      resourcePermissions: [],
      skillPermissions: [],
      permissions: ["read"]
    });
    expect(spaceSections(space, canFor(space), "space-1").map((section) => section.id)).toEqual([
      "overview"
    ]);
  });

  it("counts only the space's own knowledge", () => {
    const space = makeSpace({
      collections: [makeCollection(), makeCollection({ id: "x", space_id: "org" })],
      integrations: [{ id: "i1", space_id: "space-1" }]
    });
    expect(ownKnowledgeCount(space)).toBe(2);
  });
});

describe("spaceRoute", () => {
  it("renders the chat full-bleed", () => {
    expect(spaceRoute(["chat"])).toEqual({ kind: "chat" });
  });

  it("marks a tab's own page and the pages below it", () => {
    expect(spaceRoute(["knowledge"])).toEqual({
      kind: "page",
      section: "knowledge",
      isSectionRoot: true
    });
    expect(spaceRoute(["knowledge", "collections", "c1"])).toEqual({
      kind: "page",
      section: "knowledge",
      isSectionRoot: false
    });
    expect(spaceRoute(["assistants", "a1", "edit"])).toMatchObject({
      section: "assistants",
      isSectionRoot: false
    });
    expect(spaceRoute(["group-chats", "g1", "edit"])).toMatchObject({
      section: "assistants",
      isSectionRoot: false
    });
    expect(spaceRoute([])).toEqual({ kind: "page", section: null, isSectionRoot: false });
  });
});

describe("spaceNameIsPageHeading", () => {
  const shared = { organization: false };

  it("is the h1 on a tab's own page only", () => {
    expect(
      spaceNameIsPageHeading({ kind: "page", section: "overview", isSectionRoot: true }, shared)
    ).toBe(true);
    expect(
      spaceNameIsPageHeading({ kind: "page", section: "knowledge", isSectionRoot: false }, shared)
    ).toBe(false);
  });

  it("leaves the h1 to the organization Skills page", () => {
    expect(
      spaceNameIsPageHeading(
        { kind: "page", section: "skills", isSectionRoot: true },
        { organization: true }
      )
    ).toBe(false);
    expect(
      spaceNameIsPageHeading({ kind: "page", section: "skills", isSectionRoot: true }, shared)
    ).toBe(true);
  });
});
