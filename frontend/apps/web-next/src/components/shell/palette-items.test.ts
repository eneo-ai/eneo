import { describe, expect, it } from "vitest";
import type { RecentConversation } from "@/lib/api/conversations";
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

const PERSONAL_SPACE = { id: "p", name: "Personal", personal: true, organization: false };
const UPPHANDLING = { id: "s1", name: "Upphandling", personal: false, organization: false };

function conversation(
  id: string,
  name: string,
  partner: RecentConversation["partner"],
  space: RecentConversation["space"]
): RecentConversation {
  const at = "2026-09-26T10:00:00Z";
  return { id, name, created_at: at, last_activity_at: at, partner, space };
}

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
            apps: { items: [{ id: "app1", name: "Avtalsanalys" }] }
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
    conversation(
      "c1",
      "Upphandlingsanalys mot LOU",
      { type: "assistant", id: "a1", name: "Upphandlingsassistenten" },
      UPPHANDLING
    ),
    conversation("c2", "  ", { type: "default-assistant", id: "d", name: "Eneo" }, PERSONAL_SPACE),
    conversation(
      "c3",
      "Veckomöte",
      { type: "group-chat", id: "g1", name: "Inköpsrådet" },
      UPPHANDLING
    )
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

  it("lists what the Assistenter page lists: the personal assistant first, then assistants and apps", () => {
    const assistants = buildPaletteEntries(data, member, t).filter(
      (entry) => entry.group === "assistants"
    );
    expect(assistants.map((entry) => [entry.id, entry.action])).toEqual([
      ["personal-assistant:default", { type: "navigate", href: "/spaces/personal/chat" }],
      ["assistant:a1", { type: "navigate", href: "/dashboard/a1?tab=chat" }],
      ["assistant:a2", { type: "navigate", href: "/dashboard/a2?tab=chat" }],
      ["app:app1", { type: "navigate", href: "/dashboard/app/app1" }]
    ]);
    expect(assistants.map((entry) => entry.subtitle)).toEqual([
      "personal",
      "shell_palette_assistant_in_space(Upphandling)",
      "shell_palette_assistant_in_space(Upphandling)",
      "shell_catalog_app_in_space(Upphandling)"
    ]);
    expect(assistants[3]?.visual).toEqual({
      type: "entity",
      id: "app1",
      name: "Avtalsanalys",
      glyph: "app"
    });
  });

  it("opens conversations in their chat, says who they are with and names untitled ones", () => {
    const entries = buildPaletteEntries(data, member, t);
    const conversations = entries.filter((entry) => entry.group === "conversations");
    // Each carries when it was last active, for the row's time.
    expect(conversations.map((entry) => entry.activeAt)).toEqual(
      data.conversations.map((conversation) => conversation.last_activity_at)
    );
    expect(conversations.map((entry) => [entry.label, entry.subtitle, entry.action])).toEqual([
      [
        "Upphandlingsanalys mot LOU",
        "recent_partner_in_space(Upphandlingsassistenten,Upphandling)",
        { type: "navigate", href: "/spaces/s1/chat?type=assistant&id=a1&session_id=c1" }
      ],
      [
        "shell_untitled_conversation",
        "personal_assistant",
        { type: "navigate", href: "/spaces/personal/chat?session_id=c2" }
      ],
      [
        "Veckomöte",
        "recent_partner_in_space(Inköpsrådet,Upphandling)",
        { type: "navigate", href: "/spaces/s1/chat?type=group-chat&id=g1&session_id=c3" }
      ]
    ]);
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

  it("matches labels, subtitles and keywords case-insensitively, in group order", async () => {
    const entries = buildPaletteEntries(data, admin, t);
    const ids = (await searchEntries(entries, "UPPH")).map((entry) => entry.id);
    // a2, the app, c3 and the website match through the space name in their subtitle.
    expect(ids).toEqual([
      "assistant:a1",
      "assistant:a2",
      "app:app1",
      "space:s1",
      "conversation:c1",
      "conversation:c3",
      "collection:col1",
      "website:w1"
    ]);
    expect(await searchEntries(entries, "modeller")).toEqual([]);
    expect((await searchEntries(entries, "models")).map((entry) => entry.id)).toEqual([
      "admin:/admin/models"
    ]);
  });

  it("caps each group and shows the bootstrap set for an empty query", async () => {
    const many = Array.from({ length: 10 }, (_, index) =>
      conversation(
        `conversation:${index}`,
        `Samtal ${index}`,
        { type: "default-assistant", id: "d", name: "Eneo" },
        PERSONAL_SPACE
      )
    );
    const entries = buildPaletteEntries({ ...data, conversations: many }, member, t);
    const found = await searchEntries(entries, "samtal");
    expect(found).toHaveLength(6);
    expect(await searchEntries(entries, "  ")).toEqual(bootstrapEntries(entries));
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
