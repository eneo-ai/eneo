/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type AdminWidgetReview, type Widget, type WidgetPolicy } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import sv from "../../../../../../messages/sv.json";
import "../../../../../app.css";

const navigation = vi.hoisted(() => ({
  invalidate: vi.fn(),
  invalidateAll: vi.fn()
}));
const api = vi.hoisted(() => ({
  activate: vi.fn(),
  pause: vi.fn(),
  archive: vi.fn(),
  declineActivationRequest: vi.fn(),
  previewToken: vi.fn(),
  join: vi.fn()
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
// Messages read as their keys, or as the real Swedish text where length matters.
const i18n = vi.hoisted(() => ({ catalog: null as Record<string, string> | null }));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: navigation.invalidate,
  invalidateAll: navigation.invalidateAll,
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin/widgets/w1"), state: {} }
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    widgets: {
      activate: api.activate,
      pause: api.pause,
      archive: api.archive,
      declineActivationRequest: api.declineActivationRequest
    },
    spaces: { admin: { join: api.join } }
  })
}));
vi.mock("$lib/components/toast", () => ({ toast }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) => {
        const text = i18n.catalog?.[String(key)];
        if (text) return text.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? ""));
        return params ? `${String(key)}(${Object.values(params).join("|")})` : String(key);
      }
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import ReviewPage from "./+page.svelte";

const policy: WidgetPolicy = {
  max_daily_token_budget: 1_000_000,
  min_retention_days: 0,
  max_retention_days: 90,
  allow_bot_protection_none: false
};

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    public_id: "wgt_1",
    space_id: "s1",
    target_type: "assistant",
    target_id: "a1",
    status: "draft",
    token_generation: 1,
    revision: 7,
    name: "Bygglovschatt",
    texts: {
      title: "Frågor om bygglov",
      subtitle: "Du chattar med en AI-assistent. Svaren kan innehålla fel.",
      welcome: "Hej! Vad vill du veta om bygglov?",
      suggested_questions: ["Behöver jag bygglov för en altan?"],
      footer_text: "Skriv inga personuppgifter.",
      footer_link_url: "https://www.kommun.se/integritet",
      footer_link_label: "Integritetspolicy"
    },
    theme: { primary_color: "#1F4E79", color_scheme: "light", radius: 12 },
    limits: {
      daily_token_budget: 500_000,
      messages_per_visitor_10min: 10,
      messages_per_ip_hour: 60
    },
    privacy: { retention_days: 30, store_feedback_text: false },
    language: "sv",
    allowed_origins: ["https://www.kommun.se", "https://bygglov.kommun.se"],
    bot_protection: "altcha",
    show_sources: true,
    show_tool_activity: false,
    activation_blockers: [],
    activation_requested_at: "2026-09-24T08:30:00Z",
    activation_requested_by_user_id: "u2",
    created_at: "2026-09-20T08:00:00Z",
    updated_at: "2026-09-24T08:30:00Z",
    ...overrides
  } as Widget;
}

function review(overrides: Partial<AdminWidgetReview> = {}): AdminWidgetReview {
  return {
    widget: widget(),
    space: { id: "s1", name: "Samhällsbyggnad" },
    space_kind: "shared",
    space_security_classification: { id: "c1", name: "Intern", security_level: 2 },
    target: {
      assistant: {
        id: "a1",
        name: "Bygglovsassistenten",
        description: null,
        published: true,
        is_default: false,
        updated_at: "2026-09-20",
        completion_model: { id: "m1", name: "GPT-5", hosting: "eu" },
        instructions: "Svara bara på frågor om bygglov. Hänvisa till kommunens kundtjänst.",
        knowledge_mode: "tool",
        knowledge: [],
        attachment_count: 0,
        mcp_servers: [],
        capabilities: ["web_search"],
        insight_enabled: false,
        logging_enabled: false,
        data_retention_days: null,
        widgets: [{ id: "w1", name: "Bygglovschatt", status: "draft" }]
      },
      knowledge: [
        {
          id: "k1",
          name: "Bygglovshandboken",
          kind: "collection",
          item_count: 42,
          size_bytes: 1_000_000,
          requires_login: false,
          auto_disabled: false,
          used_by: []
        }
      ],
      visitor_mcp_servers: [{ id: "mcp1", name: "Kartverktyget" }],
      visitor_capabilities: ["web_search"]
    },
    created_by: { id: "u3", name: "Per Persson", email: "per@kommun.se" },
    activated_by: null,
    activation_requested_by: { id: "u2", name: "Anna Svensson", email: "anna@kommun.se" },
    activation_declined_by: null,
    viewer_role: null,
    viewer_membership: {
      via_groups: [],
      joinable_roles: ["viewer", "editor", "admin"],
      can_leave: false
    },
    usage: {
      questions_7d: 0,
      questions_30d: 0,
      blocked_30d: 0,
      helpful_30d: 0,
      unhelpful_30d: 0,
      last_activity: null
    },
    ...overrides
  } as AdminWidgetReview;
}

const admin = { id: "me", predefined_roles: [{ permissions: ["admin", "widgets"] }] };

/** Page.Main sizes itself to its container, which the app shell normally gives a height. */
function shell(): HTMLElement {
  const target = document.createElement("div");
  target.className = "flex h-[900px] flex-col";
  document.body.append(target);
  return target;
}

function renderPage(data: { review: AdminWidgetReview | null; policy?: WidgetPolicy | null }) {
  const eneo = { widgets: { previewToken: api.previewToken } };
  const result = render(ReviewPage, {
    target: shell(),
    props: { data: { policy, eneo, user: admin, ...data } as never }
  });
  /** What the next invalidate("admin:widget-review") reloads. */
  const reloadWith = (next: AdminWidgetReview) =>
    navigation.invalidate.mockImplementationOnce(async () => {
      await result.rerender({ data: { policy, eneo, user: admin, review: next } as never });
    });
  return { ...result, reloadWith };
}

const statusHeading = () => page.getByRole("heading", { level: 2, name: "widget_admin_status" });
const dialog = () => page.getByRole("alertdialog");

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" | ");
}

async function settled() {
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
}

async function axeViolations(context: Element | Document = document) {
  await settled();
  const result = await axe.run(context, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    },
    // A page rendered without the app shell has no page landmarks around it.
    rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html}`)
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  navigation.invalidate.mockResolvedValue(undefined);
  navigation.invalidateAll.mockResolvedValue(undefined);
  api.previewToken.mockImplementation(() => new Promise(() => {}));
  i18n.catalog = null;
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  document.body.classList.remove("bg-primary");
  delete document.documentElement.dataset.theme;
});

describe("widget review page", () => {
  test("is headed by the widget and one section per question the review answers", async () => {
    renderPage({ review: review({ widget: widget({ activated_at: "2026-09-01T08:00:00Z" }) }) });
    await expect
      .element(page.getByRole("heading", { level: 1, name: "Bygglovschatt" }))
      .toBeVisible();
    for (const name of [
      "widget_admin_status",
      "widget_review_where",
      "widget_review_what_visitors_see",
      "widget_review_access",
      "widget_review_privacy",
      "usage",
      "widget_admin_preview"
    ]) {
      await expect.element(page.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    await expect.element(page.getByRole("heading", { level: 3, name: "assistant" })).toBeVisible();
    await expect
      .element(page.getByRole("heading", { level: 4, name: /Bygglovsassistenten/ }))
      .toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "Samhällsbyggnad" }))
      .toHaveAttribute("href", "/admin/spaces/s1");
    const origins = page.getByRole("list").filter({ hasText: "https://bygglov.kommun.se" });
    await expect.element(origins).toBeVisible();
    await expect
      .element(page.getByText("Kartverktyget och widget_review_web_search"))
      .toBeVisible();
    await expect.element(page.getByText(/^Anna Svensson|^widget_review_requested\(/)).toBeVisible();
  });

  test("the assistant's instructions are behind a disclosure", async () => {
    renderPage({ review: review() });
    const toggle = page.getByRole("button", {
      name: "admin_spaces_show_instructions_named(Bygglovsassistenten)"
    });
    await expect.element(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    await expect
      .element(
        page.getByText("Svara bara på frågor om bygglov. Hänvisa till kommunens kundtjänst.")
      )
      .toBeVisible();
  });

  test("a non-member sees the static preview and can join, but no live preview is minted", async () => {
    renderPage({ review: review() });
    await expect
      .element(page.getByRole("img", { name: "widget_review_preview_alt(Bygglovschatt)" }))
      .toBeVisible();
    await expect.element(page.getByText("widget_review_preview_members_only")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "admin_spaces_join_open" }))
      .toBeVisible();
    expect(page.getByRole("button", { name: "widget_review_preview_test" }).query()).toBeNull();
    expect(page.getByTitle("widget_admin_preview_frame_title").query()).toBeNull();
    expect(api.previewToken).not.toHaveBeenCalled();
  });

  test("a member tests the answers only after asking to", async () => {
    renderPage({ review: review({ viewer_role: "viewer" }) });
    const test = page.getByRole("button", { name: "widget_review_preview_test" });
    await expect.element(test).toHaveAttribute("aria-expanded", "false");
    expect(api.previewToken).not.toHaveBeenCalled();
    expect(page.getByRole("button", { name: "admin_spaces_join_open" }).query()).toBeNull();

    await userEvent.click(test);
    await expect.element(test).toHaveAttribute("aria-expanded", "true");
    await expect
      .element(page.getByRole("heading", { level: 3, name: "widget_review_live_title" }))
      .toBeVisible();
    await vi.waitFor(() => expect(api.previewToken).toHaveBeenCalledWith({ id: "w1" }));
  });

  test("a member cannot test an unpublished assistant", async () => {
    const unpublished = review({ viewer_role: "admin" });
    unpublished.target!.assistant.published = false;
    renderPage({ review: unpublished });
    await expect.element(page.getByText("widget_review_preview_unpublished")).toBeVisible();
    expect(page.getByRole("button", { name: "widget_review_preview_test" }).query()).toBeNull();
    expect(api.previewToken).not.toHaveBeenCalled();
  });

  test("activating sends the reviewed revision and lands on the new status", async () => {
    const { reloadWith } = renderPage({ review: review() });
    api.activate.mockResolvedValue(widget({ status: "active" }));
    reloadWith(
      review({
        widget: widget({
          status: "active",
          revision: 8,
          activated_at: "2026-09-25T08:00:00Z",
          activation_requested_at: null
        }),
        activated_by: { id: "me", name: "Max", email: "max@kommun.se" }
      })
    );

    await userEvent.click(page.getByRole("button", { name: "widget_review_activate" }));
    await expect.element(dialog()).toBeVisible();
    await settled();
    // A consequential action starts on the safe choice.
    await expect.element(dialog().getByRole("button", { name: "cancel" })).toHaveFocus();
    await expect
      .element(dialog())
      .toHaveTextContent(
        /widget_review_activate_body\(https:\/\/www\.kommun\.se och https:\/\/bygglov/
      );
    await userEvent.click(dialog().getByRole("button", { name: "widget_admin_activate" }));

    await vi.waitFor(() => expect(api.activate).toHaveBeenCalledWith({ id: "w1", revision: 7 }));
    expect(toast.success).toHaveBeenCalledWith("widget_review_activated(Bygglovschatt)");
    expect(navigation.invalidate).toHaveBeenCalledWith("admin:widget-review");
    await expect.element(statusHeading()).toHaveFocus();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    await expect.element(page.getByRole("button", { name: "widget_review_pause" })).toBeVisible();
  });

  test("a widget changed since the page opened is not activated but shown anew", async () => {
    const { reloadWith } = renderPage({ review: review() });
    api.activate.mockRejectedValue(
      new EneoError("conflict", "RESPONSE", 409, 0, {
        detail: { code: "widget_revision_conflict", message: "raw" }
      })
    );
    reloadWith(review({ widget: widget({ revision: 9 }) }));

    await userEvent.click(page.getByRole("button", { name: "widget_review_activate" }));
    await userEvent.click(dialog().getByRole("button", { name: "widget_admin_activate" }));
    const alert = dialog().getByRole("alert");
    await expect.element(alert).toHaveTextContent("widget_review_stale");
    const showLatest = alert.getByRole("button", { name: "widget_review_show_latest" });
    await expect.element(showLatest).toHaveFocus();
    expect(dialog().getByRole("button", { name: "widget_admin_activate" }).query()).toBeNull();
    expect(navigation.invalidate).not.toHaveBeenCalled();

    await userEvent.click(showLatest);
    await vi.waitFor(() =>
      expect(navigation.invalidate).toHaveBeenCalledWith("admin:widget-review")
    );
    await expect.element(statusHeading()).toHaveFocus();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    expect(api.activate).toHaveBeenCalledTimes(1);
  });

  test("activation is described by what blocks it, the tenant policy included", async () => {
    // As the API sends it: the policy violations are part of activation_blockers.
    renderPage({
      review: review({
        widget: widget({
          activation_blockers: ["subtitle_empty", "retention_above_policy_maximum"],
          privacy: { retention_days: 365 }
        })
      })
    });
    const activate = page.getByRole("button", { name: "widget_review_activate" });
    await expect.element(activate).toHaveAttribute("aria-disabled", "true");
    expect((activate.element() as HTMLButtonElement).disabled).toBe(false);
    const reasons = description(activate.element());
    expect(reasons).toContain("widget_admin_blocker_subtitle_empty");
    expect(reasons).toContain("widget_admin_blocker_retention_max");
    // Playwright will not click an aria-disabled button, so a script does.
    (activate.element() as HTMLElement).click();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  });

  test("a paused widget outside a tightened policy opens and names each problem once", async () => {
    renderPage({
      review: review({
        widget: widget({
          status: "paused",
          activated_at: "2026-09-01T08:00:00Z",
          activation_requested_at: null,
          limits: { daily_token_budget: 2_000_000 },
          privacy: { retention_days: 365 },
          activation_blockers: [
            "daily_token_budget_exceeds_policy",
            "retention_above_policy_maximum"
          ]
        })
      })
    });
    const problems = document.getElementById("review-blockers");
    await expect.element(page.getByRole("button", { name: "widget_review_resume" })).toBeVisible();
    expect([...problems!.querySelectorAll("li")].map((item) => item.textContent)).toEqual([
      "widget_admin_blocker_budget_policy",
      "widget_admin_blocker_retention_max"
    ]);
  });

  test("a request that was sent back is not also said to be missing", async () => {
    renderPage({
      review: review({
        widget: widget({
          activation_requested_at: null,
          activation_declined_at: "2026-09-25T09:00:00Z",
          activation_decline_reason: "Lägg till en länk till integritetspolicyn."
        }),
        activation_declined_by: { id: "me", name: "Max", email: "max@kommun.se" }
      })
    });
    await expect.element(page.getByText(/^widget_review_returned\(/)).toBeVisible();
    expect(document.body.textContent).not.toContain("widget_review_not_requested");
  });

  test("names the visitor texts and the retentions as the editor and visitors know them", async () => {
    renderPage({ review: review() });
    const terms = [...document.querySelectorAll("dt")].map((term) => term.textContent?.trim());
    // The editor's field is called Beskrivning, as in the blocker that names it.
    expect(terms).toContain("widget_admin_text_subtitle");
    // Two retentions on one page: whose conversations each keeps.
    expect(terms).toContain("widget_review_retention_visitors");
    expect(terms).toContain("widget_review_retention_staff");
    expect(terms).not.toContain("admin_spaces_retention");
  });

  test("sending a request back asks what needs to change first", async () => {
    const { reloadWith } = renderPage({ review: review() });
    api.declineActivationRequest.mockResolvedValue(widget({ activation_requested_at: null }));
    reloadWith(
      review({
        widget: widget({
          activation_requested_at: null,
          activation_declined_at: "2026-09-25T09:00:00Z",
          activation_decline_reason: "Lägg till en länk till integritetspolicyn."
        })
      })
    );

    await userEvent.click(page.getByRole("button", { name: "widget_review_send_back" }));
    const form = page.getByRole("dialog");
    const reason = form.getByRole("textbox", { name: /widget_review_return_label/ });
    await expect.element(reason).toHaveFocus();

    await userEvent.fill(reason, "För kort");
    await userEvent.click(form.getByRole("button", { name: "widget_review_return_confirm" }));
    await expect.element(reason).toHaveAttribute("aria-invalid", "true");
    await expect.element(reason).toHaveFocus();
    expect(api.declineActivationRequest).not.toHaveBeenCalled();

    await userEvent.fill(reason, "Lägg till en länk till integritetspolicyn.");
    await userEvent.click(form.getByRole("button", { name: "widget_review_return_confirm" }));
    await vi.waitFor(() =>
      expect(api.declineActivationRequest).toHaveBeenCalledWith({
        id: "w1",
        reason: "Lägg till en länk till integritetspolicyn."
      })
    );
    expect(toast.success).toHaveBeenCalledWith("widget_review_returned_toast");
    await expect.element(statusHeading()).toHaveFocus();
    await expect
      .element(page.getByText("Lägg till en länk till integritetspolicyn.", { exact: true }))
      .toBeVisible();
    expect(page.getByRole("button", { name: "widget_review_send_back" }).query()).toBeNull();
  });

  test("a request withdrawn meanwhile cannot be sent back, and the page says so", async () => {
    const { reloadWith } = renderPage({ review: review() });
    api.declineActivationRequest.mockRejectedValue(
      new EneoError("missing", "RESPONSE", 409, 0, {
        detail: { code: "widget_activation_request_missing", message: "raw" }
      })
    );
    reloadWith(review({ widget: widget({ activation_requested_at: null }) }));

    await userEvent.click(page.getByRole("button", { name: "widget_review_send_back" }));
    await userEvent.fill(
      page.getByRole("dialog").getByRole("textbox"),
      "Beskrivningen saknar AI-upplysning."
    );
    await userEvent.click(page.getByRole("button", { name: "widget_review_return_confirm" }));
    await vi.waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("widget_request_error_missing")
    );
    expect(navigation.invalidate).toHaveBeenCalledWith("admin:widget-review");
    await expect.element(statusHeading()).toHaveFocus();
    await expect.element(page.getByText("widget_review_not_requested")).toBeVisible();
  });

  test("pausing a live widget asks first and lands on the new status", async () => {
    const live = widget({
      status: "active",
      activated_at: "2026-09-01T08:00:00Z",
      activation_requested_at: null
    });
    const { reloadWith } = renderPage({ review: review({ widget: live }) });
    let paused!: () => void;
    api.pause.mockImplementation(
      () => new Promise((resolve) => (paused = () => resolve({ ...live, status: "paused" })))
    );
    reloadWith(review({ widget: { ...live, status: "paused" } }));

    await userEvent.click(page.getByRole("button", { name: "widget_review_pause" }));
    await expect.element(dialog()).toHaveTextContent("widget_admin_overview_pause_description");
    expect(api.pause).not.toHaveBeenCalled();
    await userEvent.click(dialog().getByRole("button", { name: "widget_admin_pause" }));
    await vi.waitFor(() => expect(api.pause).toHaveBeenCalledWith({ id: "w1" }));
    // A slow network shows what is happening, not only a dimmed button.
    await expect
      .element(dialog().getByRole("button", { name: "widget_review_pausing" }))
      .toHaveAttribute("aria-busy", "true");
    paused();
    await vi.waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("widget_review_paused(Bygglovschatt)")
    );
    await expect.element(statusHeading()).toHaveFocus();
    await expect.element(page.getByRole("button", { name: "widget_review_resume" })).toBeVisible();
  });

  test("archiving says so while it runs", async () => {
    renderPage({ review: review() });
    api.archive.mockImplementation(() => new Promise(() => {}));
    await userEvent.click(page.getByRole("button", { name: "widget_review_archive" }));
    await userEvent.click(dialog().getByRole("button", { name: "widget_admin_archive" }));
    await expect
      .element(dialog().getByRole("button", { name: "widget_review_archiving" }))
      .toHaveAttribute("aria-busy", "true");
  });

  test("a failed send-back stays open and says what failed and why, in one sentence", async () => {
    renderPage({ review: review() });
    api.declineActivationRequest.mockRejectedValue(
      new EneoError("Server down", "SERVER", 503, 0, {})
    );
    await userEvent.click(page.getByRole("button", { name: "widget_review_send_back" }));
    const form = page.getByRole("dialog");
    await userEvent.fill(form.getByRole("textbox"), "Lägg till en länk till integritetspolicyn.");
    await userEvent.click(form.getByRole("button", { name: "widget_review_return_confirm" }));
    const alert = form.getByRole("alert");
    await expect.element(alert).toHaveTextContent(/^widget_review_return_failed: \S/);
    expect(navigation.invalidate).not.toHaveBeenCalled();
  });

  test("an archived widget is read only", async () => {
    renderPage({
      review: review({
        widget: widget({
          status: "archived",
          activation_requested_at: null,
          activation_blockers: ["archived"]
        }),
        viewer_role: "admin"
      })
    });
    await expect.element(page.getByText("widget_review_archived_note")).toBeVisible();
    await expect
      .element(page.getByRole("heading", { level: 2, name: "widget_review_where" }))
      .toBeVisible();
    const actions = page.getByRole("button", {
      name: /widget_review_(activate|resume|pause|archive|send_back|preview_test)/
    });
    expect(actions.elements()).toHaveLength(0);
    expect(page.getByRole("link", { name: "widget_review_open_editor" }).query()).toBeNull();
  });

  test("a missing widget says so in place", async () => {
    renderPage({ review: null, policy: null });
    await expect
      .element(page.getByRole("heading", { level: 1, name: "widget_review_not_found_title" }))
      .toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "widget_review_back" }))
      .toHaveAttribute("href", "/admin/widgets");
  });
});

describe.each(["light", "dark"])("widget review accessibility (%s)", (theme) => {
  beforeEach(() => {
    document.documentElement.dataset.theme = theme;
  });

  test("the page has no violations", async () => {
    renderPage({
      review: review({
        widget: widget({
          activated_at: "2026-09-01T08:00:00Z",
          activation_blockers: ["target_not_published"]
        })
      })
    });
    await expect.element(statusHeading()).toBeVisible();
    expect(await axeViolations()).toEqual([]);
  });

  test("a paused widget's reactivation request has no violations", async () => {
    renderPage({
      review: review({
        widget: widget({ status: "paused", activated_at: "2026-09-01T08:00:00Z" })
      })
    });
    await expect.element(page.getByText("widget_admin_status_paused")).toBeVisible();
    expect(await axeViolations()).toEqual([]);
  });

  test("the activation and send-back dialogs have no violations", async () => {
    renderPage({ review: review() });
    await userEvent.click(page.getByRole("button", { name: "widget_review_activate" }));
    await expect.element(dialog()).toBeVisible();
    expect(await axeViolations(dialog().element())).toEqual([]);
    await userEvent.keyboard("{Escape}");
    await expect
      .element(page.getByRole("button", { name: "widget_review_activate" }))
      .toHaveFocus();

    await userEvent.click(page.getByRole("button", { name: "widget_review_send_back" }));
    const form = page.getByRole("dialog");
    await expect.element(form).toBeVisible();
    await userEvent.click(form.getByRole("button", { name: "widget_review_return_confirm" }));
    await expect.element(form.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
    expect(await axeViolations(form.element())).toEqual([]);
  });

  test("archiving confirms with readable colours", async () => {
    renderPage({ review: review() });
    await userEvent.click(page.getByRole("button", { name: "widget_review_archive" }));
    await expect.element(dialog()).toBeVisible();
    expect(await axeViolations(dialog().element())).toEqual([]);
  });

  test("at 400 % zoom (320 × 256 px) the send-back dialog scrolls whole, nothing cut off", async () => {
    i18n.catalog = sv;
    renderPage({ review: review() });
    await page.viewport(320, 256);
    try {
      (page.getByRole("button", { name: "Skicka tillbaka…" }).element() as HTMLElement).click();
      const form = page.getByRole("dialog");
      await expect.element(form).toBeVisible();
      await settled();
      const content = form.element() as HTMLElement;
      expect(content.getBoundingClientRect().bottom).toBeLessThanOrEqual(256);

      // Content hidden behind `overflow: hidden` cannot be scrolled to with a mouse or a finger.
      const clipping = [content, ...content.querySelectorAll<HTMLElement>("*")].filter(
        (element) =>
          !element.closest(".sr-only") &&
          element.scrollHeight > element.clientHeight + 1 &&
          getComputedStyle(element).overflowY === "hidden"
      );
      expect(clipping.map((element) => element.outerHTML.slice(0, 100))).toEqual([]);

      for (const control of [
        form.getByRole("textbox"),
        form.getByRole("button", { name: "Avbryt" }),
        form.getByRole("button", { name: "Skicka tillbaka", exact: true })
      ].map((locator) => locator.element() as HTMLElement)) {
        control.scrollIntoView({ block: "nearest" });
        const rect = control.getBoundingClientRect();
        const hit = document.elementFromPoint(
          rect.left + rect.width / 2,
          rect.top + rect.height / 2
        );
        expect(control.contains(hit), control.outerHTML.slice(0, 80)).toBe(true);
      }
    } finally {
      await page.viewport(1440, 900);
    }
  });

  test("the page reflows at 320 px in Swedish", async () => {
    i18n.catalog = sv;
    await page.viewport(320, 720);
    try {
      renderPage({
        review: review({
          viewer_role: "viewer",
          widget: widget({ name: "Bygglovsförvaltningens kundtjänstchatt" })
        })
      });
      const title = page.getByRole("heading", { level: 1 });
      await expect.element(title).toHaveTextContent("Bygglovsförvaltningens kundtjänstchatt");
      await settled();
      // The name wraps instead of being cut off.
      const heading = title.element() as HTMLElement;
      expect(heading.scrollWidth).toBeLessThanOrEqual(heading.clientWidth);
      const main = document.getElementById("global-page-container")!;
      expect(main.scrollWidth).toBeLessThanOrEqual(main.clientWidth);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(320);
    } finally {
      await page.viewport(1440, 900);
    }
  });

  test("the preview column is a Tab stop only while it has something to scroll", async () => {
    await page.viewport(1440, 900);
    renderPage({ review: review() });
    const preview = () =>
      document.querySelector<HTMLElement>('section[aria-labelledby="review-preview-title"]')!;
    await expect.element(page.getByText("widget_review_preview_members_only")).toBeVisible();
    await settled();
    expect(preview().scrollHeight).toBeLessThanOrEqual(preview().clientHeight);
    expect(preview().hasAttribute("tabindex")).toBe(false);

    try {
      // Shorter than the column's content: now it scrolls, so a keyboard must reach it.
      await page.viewport(1440, 420);
      await vi.waitFor(() => expect(preview().getAttribute("tabindex")).toBe("0"));
      expect(preview().scrollHeight).toBeGreaterThan(preview().clientHeight);
    } finally {
      await page.viewport(1440, 900);
    }
  });
});
