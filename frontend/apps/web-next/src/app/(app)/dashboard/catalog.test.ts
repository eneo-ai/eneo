import { describe, expect, it } from "vitest";
import { catalogGroups, filterCatalog } from "./catalog";
import type { Dashboard } from "./queries";

const DASHBOARD = {
  spaces: {
    items: [
      {
        id: "s1",
        name: "Upphandling",
        personal: false,
        organization: false,
        applications: {
          assistants: { items: [{ id: "a1", name: "Upphandlingsassistenten" }] },
          apps: { items: [{ id: "app1", name: "Avtalsanalys" }] }
        }
      },
      {
        id: "empty",
        name: "Tom yta",
        personal: false,
        organization: false,
        applications: { assistants: { items: [] }, apps: { items: [] } }
      },
      {
        id: "p",
        name: "Personal",
        personal: true,
        organization: false,
        default_assistant: { id: "default" },
        applications: { assistants: { items: [] }, apps: { items: [] } }
      }
    ]
  }
} as unknown as Dashboard;

const LABELS = { personal: "Personligt", personalAssistant: "Personlig assistent" };

describe("catalogGroups", () => {
  it("puts the personal space first and skips empty spaces", () => {
    const groups = catalogGroups(DASHBOARD, LABELS);
    expect(groups.map((group) => group.name)).toEqual(["Personligt", "Upphandling"]);
    expect(groups[0]?.entries).toEqual([
      {
        id: "default",
        kind: "personal-assistant",
        name: "Personlig assistent",
        href: "/spaces/personal/chat"
      }
    ]);
    expect(groups[1]?.entries.map((entry) => entry.href)).toEqual([
      "/dashboard/a1?tab=chat",
      "/dashboard/app/app1"
    ]);
  });

  it("filters by entry name or space name", () => {
    const groups = catalogGroups(DASHBOARD, LABELS);
    expect(
      filterCatalog(groups, "avtal").flatMap((group) => group.entries.map((e) => e.id))
    ).toEqual(["app1"]);
    expect(filterCatalog(groups, "UPPHANDLING")[0]?.entries).toHaveLength(2);
    expect(filterCatalog(groups, "zzz")).toEqual([]);
  });
});
