import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { AdminSpaceAssistant, AdminSpaceKnowledgeSource } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin/spaces/space-1?tab=assistants"), state: {} }
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import AssistantConfigCard from "./AssistantConfigCard.svelte";

const INSTRUCTIONS = "Du är kommunens rådgivare.\n\n  - Svara kort.\n  - Hänvisa till källan.";

function assistant(patch: Partial<AdminSpaceAssistant> = {}): AdminSpaceAssistant {
  return {
    id: "a1",
    name: "Rådgivaren",
    description: "Svarar på frågor om ekonomiska rutiner.",
    published: true,
    is_default: false,
    updated_at: "2026-09-20T10:00:00Z",
    completion_model: { id: "m1", name: "GPT-5", hosting: "swe", org: "OpenAI" },
    instructions: INSTRUCTIONS,
    knowledge_mode: "tool",
    knowledge: [
      { id: "k1", name: "Rutiner", kind: "collection", from_organization: false },
      { id: "k2", name: "Kommunens webbplats", kind: "website", from_organization: true },
      {
        id: "k3",
        name: null,
        kind: "integration",
        integration_type: "onedrive",
        integration_item: "folder",
        from_organization: false
      },
      {
        id: "k4",
        name: null,
        kind: "integration",
        integration_type: "sharepoint",
        integration_item: "file",
        from_organization: false
      }
    ],
    attachment_count: 3,
    mcp_servers: [{ id: "s1", name: "Kalender" }],
    capabilities: ["web_search"],
    insight_enabled: true,
    logging_enabled: false,
    data_retention_days: 30,
    widgets: [{ id: "w1", name: "Kundtjänst", status: "draft", activation_requested_at: null }],
    ...patch
  };
}

/** The `dd` next to the `dt` with the given text. */
function definition(term: string): Element | null {
  const dt = [...document.querySelectorAll("dt")].find(
    (element) => element.textContent?.trim() === term
  );
  return dt?.nextElementSibling ?? null;
}

function value(term: string): string {
  return definition(term)?.textContent?.replace(/\s+/g, " ").trim() ?? "(missing)";
}

/** The items listed in the `dd` next to the `dt` with the given text. */
function listed(term: string): string[] {
  return [...(definition(term)?.querySelectorAll("li") ?? [])].map(
    (item) => item.textContent?.replace(/\s+/g, " ").trim() ?? ""
  );
}

async function axeViolations() {
  const result = await axe.run(document, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    },
    // A card rendered on its own has no page landmarks around it.
    rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html}`)
  );
}

beforeEach(() => {
  delete document.documentElement.dataset.theme;
  // The app shell paints the page; without it dark text is measured on white.
  document.body.classList.add("bg-primary");
});

afterEach(() => document.body.classList.remove("bg-primary"));

describe("AssistantConfigCard", () => {
  test("is an article named by its heading, at the level the page asks for", async () => {
    render(AssistantConfigCard, { assistant: assistant(), headingLevel: 4 });

    const article = page.getByRole("article", { name: "Rådgivaren" });
    await expect.element(article).toBeVisible();
    await expect.element(page.getByRole("heading", { level: 4, name: "Rådgivaren" })).toBeVisible();
    await expect.element(article).toHaveTextContent("admin_spaces_published");
    await expect.element(article).toHaveTextContent("Svarar på frågor om ekonomiska rutiner.");
  });

  test("lists the configuration as term and value pairs", async () => {
    render(AssistantConfigCard, { assistant: assistant() });

    for (const dl of document.querySelectorAll("dl")) {
      for (const group of dl.children) {
        expect(group.tagName).toBe("DIV");
        expect([...group.children].map((child) => child.tagName)).toEqual(["DT", "DD"]);
      }
    }
    expect(value("model")).toBe("GPT-5 · hosting_swe");
    expect(value("tools")).toBe("Kalender och web_search");
    expect(value("admin_spaces_attachments")).toBe("files(3)");
    expect(value("admin_spaces_retention")).toBe("admin_spaces_retention_days(30)");
    expect(value("insights")).toBe("admin_spaces_insights_on");
    expect(value("admin_spaces_logging")).toBe("admin_spaces_off");
  });

  test("names knowledge by kind, marks inherited sources and never names a file or folder", async () => {
    render(AssistantConfigCard, { assistant: assistant() });

    expect(listed("knowledge")).toEqual([
      "Rutiner admin_spaces_kind_collection",
      "Kommunens webbplats admin_spaces_kind_website · admin_spaces_from_org",
      "admin_spaces_onedrive_name",
      "admin_spaces_sharepoint_file"
    ]);
  });

  test("shows document counts when the sources carry them", async () => {
    const knowledge: AdminSpaceKnowledgeSource[] = [
      {
        id: "k1",
        name: "Rutiner",
        kind: "collection",
        item_count: 1,
        size_bytes: 10,
        requires_login: false,
        auto_disabled: false,
        used_by: []
      },
      {
        id: "k2",
        name: "Intranätet",
        kind: "integration",
        integration_type: "sharepoint",
        item_count: 1200,
        size_bytes: 10,
        requires_login: false,
        auto_disabled: false,
        used_by: []
      }
    ];
    render(AssistantConfigCard, { assistant: assistant(), knowledge });

    expect(listed("knowledge")).toEqual([
      "Rutiner admin_spaces_kind_collection · admin_spaces_knowledge_documents_one",
      "Intranätet admin_spaces_kind_sharepoint · admin_spaces_knowledge_documents(1 200)"
    ]);
  });

  test("says what is empty or inherited instead of leaving a blank", async () => {
    render(AssistantConfigCard, {
      assistant: assistant({
        completion_model: null,
        knowledge: [],
        attachment_count: 1,
        mcp_servers: [],
        capabilities: [],
        data_retention_days: null,
        widgets: [],
        instructions: "   "
      })
    });

    expect(value("model")).toBe("none");
    expect(value("knowledge")).toBe("admin_spaces_none");
    expect(value("admin_spaces_attachments")).toBe("admin_spaces_files_one");
    expect(value("tools")).toBe("admin_spaces_none");
    expect(value("admin_spaces_retention")).toBe("admin_spaces_retention_space");
    expect(value("admin_spaces_widget")).toBe("none");
    await expect.element(page.getByText("admin_spaces_no_instructions")).toBeVisible();
    expect(page.getByRole("button").elements()).toHaveLength(0);
  });

  test("links the widget to its review with a name that starts from what it shows", async () => {
    render(AssistantConfigCard, { assistant: assistant() });

    const link = page.getByRole("link", { name: "admin_spaces_widget_review_named(Kundtjänst)" });
    await expect.element(link).toHaveAttribute("href", "/admin/widgets/w1");
    await expect.element(link).toHaveTextContent("Kundtjänst");
    expect(value("admin_spaces_widget")).toBe("Kundtjänst · widget_admin_status_draft");
  });

  test("lists every widget of the assistant in the order the API gives, active first", async () => {
    const widget = (id: string, name: string, status: "active" | "paused" | "draft") => ({
      id,
      name,
      status,
      activation_requested_at: null
    });
    render(AssistantConfigCard, {
      assistant: assistant({
        widgets: [
          widget("w2", "Öppen", "active"),
          widget("w3", "Vilande", "paused"),
          widget("w1", "Alfa", "draft")
        ]
      })
    });

    expect(listed("widget_admin_nav")).toEqual([
      "Öppen · widget_admin_status_active",
      "Vilande · widget_admin_status_paused",
      "Alfa · widget_admin_status_draft"
    ]);
    const links = page.getByRole("link", { name: /^admin_spaces_widget_review_named/ }).elements();
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/widgets/w2",
      "/admin/widgets/w3",
      "/admin/widgets/w1"
    ]);
  });

  test("leaves the widgets out when the page is one widget's review", async () => {
    render(AssistantConfigCard, { assistant: assistant(), showWidget: false });
    expect(value("admin_spaces_widget")).toBe("(missing)");
    expect(value("widget_admin_nav")).toBe("(missing)");
  });

  test("keeps the instructions collapsed until asked, then shows them as written", async () => {
    render(AssistantConfigCard, { assistant: assistant() });

    const show = page.getByRole("button", {
      name: "admin_spaces_show_instructions_named(Rådgivaren)"
    });
    await expect.element(show).toHaveAttribute("aria-expanded", "false");
    await expect.element(show).toHaveTextContent("admin_spaces_show_instructions");
    const panel = document.getElementById(show.element().getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeNull();
    expect(panel!.hidden).toBe(true);

    await show.click();

    const hide = page.getByRole("button", {
      name: "admin_spaces_hide_instructions_named(Rådgivaren)"
    });
    await expect.element(hide).toHaveAttribute("aria-expanded", "true");
    await expect.element(hide).toHaveTextContent("admin_spaces_hide_instructions");
    expect(panel!.hidden).toBe(false);
    expect(panel!.textContent).toBe(INSTRUCTIONS);
    expect(getComputedStyle(panel!).whiteSpace).toBe("pre-wrap");
    expect(panel!.getAnimations()).toHaveLength(0);
  });

  test("reflows at 320 px with long unbroken names and instructions", async () => {
    await page.viewport(320, 640);
    try {
      const long = "Långtnamnutanmellanslagsomintefårtryckaututanförkortet".repeat(2);
      render(AssistantConfigCard, {
        assistant: assistant({ name: long, instructions: long.repeat(3) })
      });
      await page.getByRole("button", { name: /admin_spaces_show_instructions_named/ }).click();

      const article = page.getByRole("article").element() as HTMLElement;
      expect(article.getBoundingClientRect().right).toBeLessThanOrEqual(320);
      const outside = [...article.querySelectorAll<HTMLElement>("*")].filter(
        (element) => element.getBoundingClientRect().right > 321
      );
      expect(outside.map((element) => element.outerHTML.slice(0, 80))).toEqual([]);
    } finally {
      await page.viewport(1280, 720);
    }
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule with the instructions open (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(AssistantConfigCard, { assistant: assistant({ is_default: true, published: false }) });
      await page.getByRole("button", { name: /admin_spaces_show_instructions_named/ }).click();

      expect(await axeViolations()).toEqual([]);
    }
  );
});
