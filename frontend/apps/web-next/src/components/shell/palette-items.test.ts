import { describe, expect, it } from "vitest";
import { adminNavGroups } from "./admin-nav-items";
import {
  bootstrapEntries,
  buildPaletteEntries,
  searchEntries,
  splitMatch,
  type PaletteData,
  type PalettePermissions
} from "./palette-items";

const t = (key: string, values?: Record<string, string>) =>
  values ? `${key}(${Object.values(values).join(",")})` : key;

const data = {
  dashboard: {
    spaces: {
      items: [
        {
          id: "p",
          name: "Personal",
          personal: true,
          organization: false,
          default_assistant: { id: "default" },
          applications: { assistants: { items: [] }, apps: { items: [] } }
        },
        {
          id: "s1",
          name: "Upphandling",
          personal: false,
          organization: false,
          applications: {
            assistants: {
              items: [
                { id: "a1", name: "Upphandlingsassistenten" },
                { id: "a2", name: "Avtalsgranskaren" }
              ]
            },
            apps: { items: [] }
          }
        }
      ]
    }
  },
  spaces: [
    {
      id: "s1",
      name: "Upphandling",
      description: "Inköp och avtal",
      personal: false,
      organization: false
    },
    { id: "org", name: "Org", description: null, personal: false, organization: true }
  ],
  conversations: [
    { id: "c1", name: "Upphandlingsanalys mot LOU" },
    { id: "c2", name: "  " }
  ],
  currentSpace: {
    routeId: "s1",
    space: {
      name: "Upphandling",
      personal: false,
      knowledge: {
        groups: { items: [{ id: "col1", name: "Upphandlingspolicy" }] },
        websites: { items: [{ id: "w1", name: null, url: "https://lou.example.se" }] }
      }
    }
  }
} as unknown as PaletteData;

const member: PalettePermissions = { canCreateSpace: false, isAdmin: false, adminGroups: [] };
const admin: PalettePermissions = {
  canCreateSpace: true,
  isAdmin: true,
  adminGroups: adminNavGroups({ usingTemplates: false, canManageModules: false })
};

describe("buildPaletteEntries", () => {
  it("lists assistants, spaces, conversations, knowledge and actions in that order", () => {
    const entries = buildPaletteEntries(data, member, t);
    const groups = [...new Set(entries.map((entry) => entry.group))];
    expect(groups).toEqual(["assistants", "spaces", "conversations", "knowledge", "actions"]);
  });

  it("opens the personal assistant in the personal chat and others in their chat", () => {
    const entries = buildPaletteEntries(data, member, t);
    expect(entries.find((entry) => entry.id === "assistant:default")?.action).toEqual({
      type: "navigate",
      href: "/spaces/personal/chat"
    });
    const upphandling = entries.find((entry) => entry.id === "assistant:a1");
    expect(upphandling?.action).toEqual({ type: "navigate", href: "/dashboard/a1?tab=chat" });
    expect(upphandling?.subtitle).toBe("shell_palette_assistant_in_space(Upphandling)");
  });

  it("links conversations with ?session_id= and names untitled ones", () => {
    const entries = buildPaletteEntries(data, member, t);
    const conversations = entries.filter((entry) => entry.group === "conversations");
    expect(conversations.map((entry) => entry.action)).toEqual([
      { type: "navigate", href: "/spaces/personal/chat?session_id=c1" },
      { type: "navigate", href: "/spaces/personal/chat?session_id=c2" }
    ]);
    expect(conversations[1]?.label).toBe("shell_untitled_conversation");
  });

  it("offers the current space's collections and websites", () => {
    const knowledge = buildPaletteEntries(data, member, t).filter(
      (entry) => entry.group === "knowledge"
    );
    expect(knowledge.map((entry) => [entry.label, entry.action])).toEqual([
      ["Upphandlingspolicy", { type: "navigate", href: "/spaces/s1/knowledge/collections/col1" }],
      ["https://lou.example.se", { type: "navigate", href: "/spaces/s1/knowledge/websites/w1" }]
    ]);
  });

  it("gates Skapa yta, the organisation and admin pages", () => {
    const forMember = buildPaletteEntries(data, member, t).map((entry) => entry.id);
    expect(forMember).not.toContain("action:create-space");
    expect(forMember).not.toContain("space:organization");
    expect(forMember.some((id) => id.startsWith("admin:"))).toBe(false);

    const forAdmin = buildPaletteEntries(data, admin, t);
    expect(forAdmin.find((entry) => entry.id === "action:create-space")?.action).toEqual({
      type: "create-space"
    });
    const models = forAdmin.find((entry) => entry.id === "admin:/admin/models");
    expect(models?.label).toBe("shell_palette_admin_page(models)");
    expect(forAdmin.find((entry) => entry.id === "admin:/admin/templates")).toBeUndefined();
  });
});

describe("bootstrapEntries / searchEntries", () => {
  it("keeps the empty palette short: no admin pages or knowledge until the user types", () => {
    const shown = bootstrapEntries(buildPaletteEntries(data, admin, t));
    expect(shown.some((entry) => entry.id.startsWith("admin:"))).toBe(false);
    expect(shown.some((entry) => entry.group === "knowledge")).toBe(false);
  });

  it("matches labels, subtitles and keywords case-insensitively", () => {
    const entries = buildPaletteEntries(data, admin, t);
    const ids = searchEntries(entries, "UPPH").map((entry) => entry.id);
    // a2 and the website match through the space name in their subtitle.
    expect(ids).toEqual([
      "assistant:a1",
      "assistant:a2",
      "space:s1",
      "conversation:c1",
      "collection:col1",
      "website:w1"
    ]);
    expect(searchEntries(entries, "modeller").map((entry) => entry.id)).toEqual([]);
    expect(searchEntries(entries, "models").map((entry) => entry.id)).toEqual([
      "admin:/admin/models"
    ]);
  });

  it("ranks labels that start with the query first within a group", () => {
    const entries = buildPaletteEntries(data, admin, t);
    const assistants = searchEntries(entries, "avtal").filter(
      (entry) => entry.group === "assistants"
    );
    expect(assistants.map((entry) => entry.id)).toEqual(["assistant:a2"]);
  });
});

describe("splitMatch", () => {
  it("returns the matched part for highlighting, keeping the original case", () => {
    expect(splitMatch("Upphandlingsanalys", "upph")).toEqual({
      before: "",
      match: "Upph",
      after: "andlingsanalys"
    });
    expect(splitMatch("Jämför upphandling", "UPPH")?.before).toBe("Jämför ");
    expect(splitMatch("Avtal", "x")).toBeNull();
    expect(splitMatch("Avtal", " ")).toBeNull();
  });
});
