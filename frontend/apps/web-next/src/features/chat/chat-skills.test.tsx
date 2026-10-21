// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ChatSkills } from "./chat-skills";
import { awaitPartnerUpdates, hasPendingPartnerUpdates } from "./partner-updates";

type Configuration = Schema<"AssistantSkillConfigurationPublic">;
type Summary = Schema<"AssistantSkillBindingSummary">;

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: {
      id: "personal-space",
      personal: true,
      default_assistant: { id: "assistant-1", completion_model: { id: "model-1" } }
    },
    routeId: "personal",
    can: () => true
  })
}));

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const refused = (status: number, body: unknown) =>
  Promise.resolve({ data: undefined, error: body, response: new Response(null, { status }) });

function summary(
  overrides: Partial<Summary> & Pick<Summary, "skill_id" | "display_name">
): Summary {
  return {
    skill_revision_id: `${overrides.skill_id}-r2`,
    attachable_revision_id: `${overrides.skill_id}-r2`,
    slug: overrides.skill_id,
    revision_number: 2,
    attachable_revision_number: 2,
    description: "",
    content_digest: "digest",
    position: 0,
    is_active: true,
    source: "space",
    execution_blocked: false,
    activation_mode: "always",
    ...overrides
  };
}

function librarySkill(id: string, name: string, description: string) {
  return {
    id,
    space_id: "personal-space",
    slug: id,
    is_active: true,
    current_revision_id: `${id}-r2`,
    current_revision_number: 2,
    display_name: name,
    description,
    content_digest: "digest",
    created_by_user_id: "user-1",
    created_at: "2026-10-01T08:00:00Z",
    updated_at: "2026-10-01T08:00:00Z"
  };
}

const klarsprak = summary({
  skill_id: "klarsprak",
  display_name: "Klarspråk",
  description: "Skriver enkelt och tydligt",
  source: "organization"
});
const answers = summary({
  skill_id: "answers",
  display_name: "Mina svarspreferenser",
  description: "Korta svar, punktlistor, du-tilltal"
});
const library = [
  librarySkill("answers", "Mina svarspreferenser", "Korta svar, punktlistor, du-tilltal"),
  librarySkill("notes", "Mötesanteckningar", "Strukturerar anteckningar till protokoll")
];

/** What the server has saved for the personal chat. */
let configuration: Configuration;
/** The personal space's Skills, served page by page and searched by `q`. */
let skills: ReturnType<typeof librarySkill>[];
/** The library page (by cursor) that fails, if any. */
let failingPage: string | null = null;
/** Lets a save a test held back go, so the shared queue never stays blocked. */
let releaseSave: (() => void) | null = null;

type SentBinding = { skill_id: string; skill_revision_id: string; activation_mode?: string };
type Request = {
  params?: { query?: { limit?: number; cursor?: string | null; q?: string } };
  body?: { skill_bindings?: SentBinding[] };
};

/** Saves the sent list as the server does: it becomes the personal chat's bindings. */
function saveOnServer(init?: Request) {
  const sent = init?.body?.skill_bindings ?? [];
  configuration = {
    ...configuration,
    bindings: sent.map((binding, position) => ({
      ...(configuration.bindings.find((saved) => saved.skill_id === binding.skill_id) ??
        summary({ skill_id: binding.skill_id, display_name: binding.skill_id })),
      skill_revision_id: binding.skill_revision_id,
      activation_mode: binding.activation_mode === "on_demand" ? "on_demand" : "always",
      position
    }))
  };
  return ok({});
}

/** A save held until the test lets it go: saved (or refused) then. */
function holdSave(outcome: (init?: Request) => ReturnType<typeof ok> = saveOnServer) {
  return (_path: string, init?: Request) =>
    new Promise((resolve) => {
      releaseSave = () => resolve(outcome(init));
    });
}

beforeEach(() => {
  configuration = {
    bindings: [answers],
    organisation_bindings: [klarsprak],
    personal_layer: { status: "applied", reason: null, detail: null },
    runtime: null
  };
  skills = library;
  failingPage = null;
  api.GET.mockImplementation((path: string, init?: Request) => {
    if (path === "/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/")
      return ok(configuration);
    if (path === "/api/v1/spaces/{space_id}/skills/") {
      const { limit = 25, cursor = null, q } = init?.params?.query ?? {};
      if (failingPage !== null && cursor === failingPage) return refused(500, { message: "Boom" });
      const matching = q
        ? skills.filter((skill) =>
            `${skill.display_name} ${skill.description}`.toLowerCase().includes(q.toLowerCase())
          )
        : skills;
      const start = cursor ? Number(cursor) : 0;
      const end = start + limit;
      return ok({
        items: matching.slice(start, end),
        total_count: matching.length,
        next_cursor: end < matching.length ? String(end) : null
      });
    }
    throw new Error(`Unexpected GET ${path}`);
  });
  api.POST.mockImplementation((_path: string, init?: Request) => saveOnServer(init));
});

afterEach(async () => {
  cleanup();
  releaseSave?.();
  releaseSave = null;
  await awaitPartnerUpdates();
  vi.clearAllMocks();
  setViewport("desktop");
});

const OWN_AND_CHAT = ["personal_chat", "personal_skills"] as const;

function renderSkills(permissions: readonly string[] = OWN_AND_CHAT) {
  return renderInApp(<ChatSkills />, {
    appContext: testAppContext({ permissions: [...permissions] as never })
  });
}

/** Opens the popover (or sheet) and waits until the person's skills have loaded into it. */
async function openSkills(name = "Skills i din personliga chatt: 2") {
  fireEvent.click(await screen.findByRole("button", { name }));
  const dialog = await screen.findByRole("dialog", { name: "Skills" });
  await waitFor(() => expect(dialog.querySelector('[aria-busy="true"]')).toBeNull());
  return dialog;
}

/** The row of an own skill: its mode group and what is said about it. */
function rowOf(group: HTMLElement) {
  return group.closest("li")!;
}

describe("ChatSkills", () => {
  it("names the control with the count of skills that run and lists both layers", async () => {
    renderSkills();
    const popover = await openSkills();

    expect(within(popover).getByText("Gäller alla dina personliga chattar")).toBeTruthy();
    expect(within(popover).getByText("2 alltid · 0 vid behov")).toBeTruthy();

    const organisation = within(popover).getByRole("list", { name: "Från organisationen" });
    expect(within(organisation).getByText("Klarspråk")).toBeTruthy();
    expect(within(organisation).getByText("Vald av administratör")).toBeTruthy();
    expect(within(organisation).getByText("Alltid")).toBeTruthy();
    expect(within(organisation).queryByRole("radiogroup")).toBeNull();

    const own = within(popover).getByRole("list", { name: "Dina skills" });
    const answersMode = within(own).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });
    expect(within(answersMode).getByRole("radio", { name: "Alltid", checked: true })).toBeTruthy();
    const notesMode = within(own).getByRole("radiogroup", { name: "Läge för Mötesanteckningar" });
    expect(within(notesMode).getByRole("radio", { name: "Av", checked: true })).toBeTruthy();
    expect(
      within(notesMode)
        .getAllByRole("radio")
        .map((radio) => radio.textContent)
    ).toEqual(["Av", "Vid behov", "Alltid"]);

    expect(within(popover).getByRole("link", { name: "Hantera skills" }).getAttribute("href")).toBe(
      "/spaces/personal/skills"
    );
    expect(within(popover).getByRole("link", { name: "Skapa skill" }).getAttribute("href")).toBe(
      "/spaces/personal/skills/new"
    );
    await expectNoAxeViolations(popover);
  });

  it("saves a choice at once and makes a question sent right after wait for it", async () => {
    api.POST.mockImplementationOnce(holdSave());
    renderSkills();
    const popover = await openSkills();
    const notesMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mötesanteckningar"
    });

    fireEvent.click(within(notesMode).getByRole("radio", { name: "Vid behov" }));

    // Shown at once, while the save is still on its way.
    expect(
      await within(notesMode).findByRole("radio", { name: "Vid behov", checked: true })
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skills i din personliga chatt: 3" })).toBeTruthy();
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(hasPendingPartnerUpdates()).toBe(true);
    // The person's whole ordered list; the organisation's skills are never sent.
    expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
      params: { path: { id: "assistant-1" } },
      body: {
        skill_bindings: [
          { skill_id: "answers", skill_revision_id: "answers-r2", activation_mode: "always" },
          { skill_id: "notes", skill_revision_id: "notes-r2", activation_mode: "on_demand" }
        ]
      }
    });

    await act(async () => {
      releaseSave?.();
      await awaitPartnerUpdates();
    });
    expect(hasPendingPartnerUpdates()).toBe(false);
    expect(within(notesMode).getByRole("radio", { name: "Vid behov", checked: true })).toBeTruthy();
    expect(within(popover).getByText("2 alltid · 1 vid behov")).toBeTruthy();
  });

  it("leaves a skill out of the list when it is turned off", async () => {
    renderSkills();
    const popover = await openSkills();
    const answersMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });
    fireEvent.click(within(answersMode).getByRole("radio", { name: "Av" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
        params: { path: { id: "assistant-1" } },
        body: { skill_bindings: [] }
      })
    );
  });

  it("rolls a refused choice back and says why next to it", async () => {
    api.POST.mockImplementation(() =>
      refused(400, {
        message: "On-demand Skills are unavailable",
        eneo_error_code: 9080,
        details: { reason: "on_demand_unavailable", detail: "selective_activation_disabled" }
      })
    );
    renderSkills();
    const popover = await openSkills();
    const notesMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mötesanteckningar"
    });

    fireEvent.click(within(notesMode).getByRole("radio", { name: "Vid behov" }));

    const reason = "Din organisation har stängt av skills vid behov. Välj Alltid.";
    expect(await within(rowOf(notesMode)).findByText(reason)).toBeTruthy();
    expect(within(notesMode).getByRole("radio", { name: "Av", checked: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skills i din personliga chatt: 2" })).toBeTruthy();
  });

  it("says the change was not saved when the save fails for another reason", async () => {
    api.POST.mockImplementation(() => refused(500, { message: "Boom" }));
    renderSkills();
    const popover = await openSkills();
    const answersMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });

    fireEvent.click(within(answersMode).getByRole("radio", { name: "Vid behov" }));

    expect(
      await within(rowOf(answersMode)).findByText("Ändringen sparades inte. Försök igen.")
    ).toBeTruthy();
    expect(within(answersMode).getByRole("radio", { name: "Alltid", checked: true })).toBeTruthy();
  });

  it("forgets a refusal once the control closes", async () => {
    api.POST.mockImplementation(() => refused(500, { message: "Boom" }));
    renderSkills();
    let popover = await openSkills();
    fireEvent.click(
      within(
        within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
      ).getByRole("radio", { name: "Vid behov" })
    );
    const refusal = "Ändringen sparades inte. Försök igen.";
    expect(await within(popover).findByText(refusal)).toBeTruthy();

    // Closed with the trigger, then opened again.
    const trigger = screen.getByRole("button", { name: "Skills i din personliga chatt: 2" });
    fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("false"));
    popover = await openSkills();
    expect(within(popover).queryByText(refusal)).toBeNull();
  });

  it("fits the popover in the room above the pill, so it never covers the composer", async () => {
    renderSkills();
    const trigger = await screen.findByRole("button", { name: "Skills i din personliga chatt: 2" });
    // The pill sits 400 px down the window (jsdom has no layout of its own).
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ x: 300, y: 400, width: 96, height: 32 })
    );
    const popover = await openSkills();
    // 400 px less the popover's 4 px gap, 24 px of padding and 16 px window gutter.
    const panel = within(popover)
      .getByText("Gäller alla dina personliga chattar")
      .closest("[style*='max-height']") as HTMLElement;
    expect(panel.style.maxHeight).toBe("356px");
    // The list scrolls inside; the header and the links stay.
    const list = within(popover)
      .getByRole("list", { name: "Dina skills" })
      .closest(".overflow-y-auto");
    expect(list).not.toBeNull();
    expect(within(popover).getByRole("link", { name: "Hantera skills" })).toBeTruthy();
  });

  it("explains a paused layer and counts only the organisation's skills", async () => {
    configuration = {
      ...configuration,
      personal_layer: { status: "suspended", reason: "attachment_limit_exceeded", detail: null }
    };
    renderSkills();
    const popover = await openSkills("Skills i din personliga chatt: 1");

    expect(within(popover).getByText("Dina skills är pausade")).toBeTruthy();
    expect(
      within(popover).getByText(
        "Tillsammans med organisationens skills blir det fler än tillåtet. Stäng av några av dina skills."
      )
    ).toBeTruthy();
    expect(within(popover).getByText("1 alltid · 0 vid behov")).toBeTruthy();
    // Turning a skill off stays possible: it is how the person recovers.
    expect(
      within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
    ).toBeTruthy();
    await expectNoAxeViolations(popover);
  });

  it("offers to create a skill when the person has none", async () => {
    configuration = { ...configuration, bindings: [] };
    skills = [];
    renderSkills();
    const popover = await openSkills("Skills i din personliga chatt: 1");

    expect(
      within(popover).getByText(
        "Du har inga egna skills än. Skapa en skill för att styra hur din personliga chatt svarar."
      )
    ).toBeTruthy();
    expect(within(popover).getByRole("link", { name: "Skapa skill" })).toBeTruthy();
    expect(within(popover).queryByRole("radiogroup")).toBeNull();
  });

  it("shows choices read-only and paused when the role no longer allows own skills", async () => {
    configuration = {
      ...configuration,
      personal_layer: { status: "suspended", reason: "permission_missing", detail: null }
    };
    renderSkills(["personal_chat"]);
    const popover = await openSkills("Skills i din personliga chatt: 1");

    expect(
      within(popover).getByText(
        "Din roll tillåter inte längre egna skills. Dina val finns kvar om behörigheten kommer tillbaka."
      )
    ).toBeTruthy();
    const own = within(popover).getByRole("list", { name: "Dina skills" });
    expect(within(own).getByText("Mina svarspreferenser")).toBeTruthy();
    expect(within(own).getByText("Alltid")).toBeTruthy();
    expect(within(popover).queryByRole("radiogroup")).toBeNull();
    expect(within(popover).queryByRole("link")).toBeNull();
    expect(api.GET).not.toHaveBeenCalledWith(
      "/api/v1/spaces/{space_id}/skills/",
      expect.anything()
    );
  });

  it("is not shown without the permission when no skill is in the chat", async () => {
    configuration = { ...configuration, bindings: [], organisation_bindings: [] };
    renderSkills(["personal_chat"]);
    await waitFor(() => expect(api.GET).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByRole("button", { name: /^Skills/ })).toBeNull();
  });

  it("moves a skill to its latest version on request", async () => {
    configuration = {
      ...configuration,
      bindings: [
        {
          ...answers,
          skill_revision_id: "answers-r1",
          revision_number: 1,
          attachable_revision_id: "answers-r3",
          attachable_revision_number: 3
        }
      ]
    };
    renderSkills();
    const popover = await openSkills();
    const row = rowOf(
      within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
    );

    expect(within(row).getByText("Ny version finns")).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "Använd senaste versionen" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
        params: { path: { id: "assistant-1" } },
        body: {
          skill_bindings: [
            { skill_id: "answers", skill_revision_id: "answers-r3", activation_mode: "always" }
          ]
        }
      })
    );
  });

  it("offers no version move for a deactivated skill in the chat", async () => {
    configuration = {
      ...configuration,
      bindings: [
        {
          ...answers,
          is_active: false,
          skill_revision_id: "answers-r1",
          revision_number: 1,
          attachable_revision_id: "answers-r3",
          attachable_revision_number: 3
        }
      ]
    };
    renderSkills();
    const popover = await openSkills();
    const row = rowOf(
      within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
    );

    expect(within(row).queryByText("Ny version finns")).toBeNull();
    expect(within(row).queryByRole("button", { name: "Använd senaste versionen" })).toBeNull();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("keeps a skill an administrator blocked as it is", async () => {
    configuration = { ...configuration, bindings: [{ ...answers, execution_blocked: true }] };
    renderSkills();
    // A blocked skill does not run, so it is not counted.
    const popover = await openSkills("Skills i din personliga chatt: 1");
    const answersMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });

    expect(answersMode.getAttribute("aria-disabled")).toBe("true");
    expect(within(rowOf(answersMode)).getByText("Spärrad av administratör")).toBeTruthy();
  });

  it("opens the same choices in a bottom sheet on a phone, with search only beyond seven skills", async () => {
    setViewport("phone");
    renderSkills();
    const sheet = await openSkills();
    expect(sheet.tagName).toBe("DIALOG");
    expect(
      within(sheet).getByRole("radiogroup", { name: "Läge för Mötesanteckningar" })
    ).toBeTruthy();
    expect(within(sheet).queryByRole("textbox")).toBeNull();
    fireEvent.click(within(sheet).getByRole("button", { name: "Stäng" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Skills" })).toBeNull());
  });

  it("searches the person's skills on the server when there are more than seven", async () => {
    skills = [
      ...library,
      ...Array.from({ length: 6 }, (_, index) =>
        librarySkill(`extra-${index}`, `Mall ${index + 1}`, "Färdig struktur")
      )
    ];
    renderSkills();
    const popover = await openSkills();
    const search = within(popover).getByRole("textbox", { name: "Sök bland dina skills" });

    fireEvent.change(search, { target: { value: "möte" } });
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/", {
        params: {
          path: { space_id: "personal-space" },
          query: { limit: 25, cursor: null, q: "möte" }
        },
        signal: expect.any(AbortSignal)
      })
    );
    const own = within(popover).getByRole("list", { name: "Dina skills" });
    await waitFor(() => expect(within(own).getAllByRole("radiogroup")).toHaveLength(1));
    expect(
      within(own).getByRole("radiogroup", { name: "Läge för Mötesanteckningar" })
    ).toBeTruthy();

    fireEvent.change(search, { target: { value: "inget sådant" } });
    expect(await within(popover).findByText("Inga skills matchar sökningen.")).toBeTruthy();
  });

  it("loads one page at a time and keeps bound skills usable when a later page fails", async () => {
    // "Mina svarspreferenser" is in the chat but on the second page, which fails.
    skills = [
      ...Array.from({ length: 25 }, (_, index) =>
        librarySkill(`template-${index}`, `Mall ${index + 1}`, "Färdig struktur")
      ),
      library[0]!
    ];
    failingPage = "25";
    renderSkills();
    const popover = await openSkills();

    expect(
      api.GET.mock.calls.filter(([path]) => path === "/api/v1/spaces/{space_id}/skills/")
    ).toHaveLength(1);
    // More pages exist: the search field is there for the rest.
    expect(within(popover).getByRole("textbox", { name: "Sök bland dina skills" })).toBeTruthy();
    const answersMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });
    expect(within(answersMode).getByRole("radio", { name: "Alltid", checked: true })).toBeTruthy();

    fireEvent.click(within(popover).getByRole("button", { name: "Ladda mer" }));
    expect(await within(popover).findByRole("button", { name: "Försök igen" })).toBeTruthy();

    // The skill in the chat can still be changed.
    fireEvent.click(
      within(
        within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
      ).getByRole("radio", { name: "Av" })
    );
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
        params: { path: { id: "assistant-1" } },
        body: { skill_bindings: [] }
      })
    );
  });

  it("offers the next page when a page holds no skill that can join the chat", async () => {
    configuration = { ...configuration, bindings: [] };
    skills = [
      ...Array.from({ length: 25 }, (_, index) => ({
        ...librarySkill(`old-${index}`, `Gammal ${index + 1}`, "Avstängd"),
        is_active: false
      })),
      library[1]!
    ];
    renderSkills();
    const popover = await openSkills("Skills i din personliga chatt: 1");

    expect(within(popover).queryByText(/Du har inga egna skills än/)).toBeNull();
    fireEvent.click(within(popover).getByRole("button", { name: "Ladda mer" }));
    expect(
      await within(popover).findByRole("radiogroup", { name: "Läge för Mötesanteckningar" })
    ).toBeTruthy();
  });

  it("re-adds a skill no loaded page shows at its newest version, and keeps its version on a mode change", async () => {
    // In the chat at version 1; version 2 is the newest. Its library page isn't loaded.
    configuration = {
      ...configuration,
      bindings: [{ ...answers, skill_revision_id: "answers-r1", revision_number: 1 }]
    };
    skills = [];
    renderSkills();
    const popover = await openSkills();
    const sent = () =>
      api.POST.mock.calls.map(([, init]) => (init as Request).body?.skill_bindings);
    const choose = (label: string) =>
      fireEvent.click(
        within(
          within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
        ).getByRole("radio", { name: label })
      );

    choose("Vid behov");
    await waitFor(() =>
      expect(sent()).toEqual([
        [{ skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "on_demand" }]
      ])
    );

    api.POST.mockImplementationOnce(holdSave());
    choose("Av");
    choose("Alltid");
    await waitFor(() => expect(releaseSave).not.toBeNull());
    releaseSave!();
    await waitFor(() =>
      expect(sent().slice(1)).toEqual([
        [],
        [{ skill_id: "answers", skill_revision_id: "answers-r2", activation_mode: "always" }]
      ])
    );
  });

  it("builds each save from what is saved when its turn comes, not from what was last shown", async () => {
    renderSkills();
    const popover = await openSkills();
    // Saved meanwhile, elsewhere: the chat now also has "Mötesanteckningar".
    saveOnServer({
      body: {
        skill_bindings: [
          { skill_id: "answers", skill_revision_id: "answers-r2", activation_mode: "always" },
          { skill_id: "notes", skill_revision_id: "notes-r2", activation_mode: "on_demand" }
        ]
      }
    });

    fireEvent.click(
      within(
        within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
      ).getByRole("radio", { name: "Av" })
    );

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
        params: { path: { id: "assistant-1" } },
        body: {
          skill_bindings: [
            { skill_id: "notes", skill_revision_id: "notes-r2", activation_mode: "on_demand" }
          ]
        }
      })
    );
  });

  it("keeps an accepted change when the chat is left before the next one is saved", async () => {
    api.POST.mockImplementationOnce(holdSave());
    const { unmount } = renderSkills();
    const popover = await openSkills();
    fireEvent.click(
      within(
        within(popover).getByRole("radiogroup", { name: "Läge för Mötesanteckningar" })
      ).getByRole("radio", { name: "Alltid" })
    );
    fireEvent.click(
      within(
        within(popover).getByRole("radiogroup", { name: "Läge för Mina svarspreferenser" })
      ).getByRole("radio", { name: "Av" })
    );
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));

    // The person leaves the chat; nothing on screen reads the saved state any more.
    unmount();
    await act(async () => {
      releaseSave?.();
      await awaitPartnerUpdates();
    });

    expect(api.POST).toHaveBeenCalledTimes(2);
    expect(api.POST).toHaveBeenLastCalledWith("/api/v1/assistants/{id}/", {
      params: { path: { id: "assistant-1" } },
      body: {
        skill_bindings: [
          { skill_id: "notes", skill_revision_id: "notes-r2", activation_mode: "always" }
        ]
      }
    });
  });

  it("sends nothing when what is saved cannot be read, and says the change was not saved", async () => {
    renderSkills();
    const popover = await openSkills();
    api.GET.mockImplementation(() => refused(500, { message: "Boom" }));
    const answersMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });

    fireEvent.click(within(answersMode).getByRole("radio", { name: "Av" }));

    expect(
      await within(rowOf(answersMode)).findByText("Ändringen sparades inte. Försök igen.")
    ).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("shows a refusal only while it is the newest choice for that skill", async () => {
    const refusal = {
      message: "On-demand Skills are unavailable",
      eneo_error_code: 9080,
      details: { reason: "on_demand_unavailable", detail: "model_lacks_tool_calling" }
    };
    const reason = "Modellen kan inte använda skills vid behov. Välj Alltid eller en annan modell.";
    api.POST.mockImplementationOnce(() => refused(400, refusal))
      .mockImplementationOnce(holdSave(() => refused(400, refusal)))
      .mockImplementation((_path: string, init?: Request) => saveOnServer(init));
    renderSkills();
    const popover = await openSkills();
    const answersMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mina svarspreferenser"
    });
    const notesMode = within(popover).getByRole("radiogroup", {
      name: "Läge för Mötesanteckningar"
    });

    // Another row's refusal stays where it is.
    fireEvent.click(within(answersMode).getByRole("radio", { name: "Vid behov" }));
    expect(await within(rowOf(answersMode)).findByText(reason)).toBeTruthy();

    // "Vid behov" is still on its way (and will be refused) when "Alltid" is chosen.
    fireEvent.click(within(notesMode).getByRole("radio", { name: "Vid behov" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    fireEvent.click(within(notesMode).getByRole("radio", { name: "Alltid" }));
    await act(async () => {
      releaseSave?.();
      await awaitPartnerUpdates();
    });

    expect(api.POST).toHaveBeenCalledTimes(3);
    await waitFor(() =>
      expect(within(notesMode).getByRole("radio", { name: "Alltid", checked: true })).toBeTruthy()
    );
    expect(within(rowOf(notesMode)).queryByText(reason)).toBeNull();
    expect(within(rowOf(answersMode)).getByText(reason)).toBeTruthy();
  });
});
