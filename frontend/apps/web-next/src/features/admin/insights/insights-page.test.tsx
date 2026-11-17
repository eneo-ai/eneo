// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntlProvider } from "use-intl";
import en from "@/lib/i18n/messages/en.json";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp, testAppContext } from "@/test/render";

const counts = (user: number, widget: number, api_key: number) => ({
  total: user + widget + api_key,
  user,
  widget,
  api_key
});

const target = (id: string, name: string, overrides: Record<string, unknown> = {}) => ({
  id,
  kind: "assistant",
  name,
  space_id: `space-${id}`,
  space_name: "Bygg och miljö",
  insight_enabled: true,
  conversations: counts(0, 0, 0),
  questions: 0,
  previous: null,
  ratings: { positive: 0, negative: 0 },
  ...overrides
});

/** Every personal space's assistants together: the same whatever the filters. */
const PERSONAL = { assistants: 3, conversations: counts(40, 0, 2), questions: 90 };

/** Three targets of note, then enough unused assistants for a second page. */
const TARGETS = [
  target("t-1", "Bygglovsassistenten", {
    conversations: counts(742, 468, 74),
    questions: 2946,
    ratings: { positive: 165, negative: 47 }
  }),
  target("t-2", "Upphandlingsstöd", {
    kind: "group_chat",
    space_name: "Ekonomi",
    conversations: counts(611, 0, 0),
    questions: 900
  }),
  target("t-3", "Skolskjutsfrågor", {
    insight_enabled: false,
    ratings: null,
    conversations: counts(31, 69, 0),
    questions: 120
  }),
  ...Array.from({ length: 24 }, (_, index) => target(`u-${index}`, `Oanvänd ${index + 1}`))
];

const state = vi.hoisted(() => ({
  aggregated: "pending" as "pending" | "fail" | "ok",
  calls: [] as { path: string; query?: Record<string, string> }[],
  firstStart: ""
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, init?: { params?: { query?: Record<string, string> } }) => {
      state.calls.push({ path, query: init?.params?.query });
      const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
      switch (path) {
        case "/api/v1/analysis/counts/":
          return ok({ assistants: 3, sessions: 12, questions: 40123 });
        case "/api/v1/analysis/metadata-statistics/aggregated/":
          if (state.aggregated === "fail") {
            return Promise.reject(new EneoApiError("boom", { status: 500, code: 9024 }));
          }
          if (state.aggregated === "pending") return new Promise(() => {});
          if (!state.firstStart) state.firstStart = init!.params!.query!.start_date!;
          const previous = init!.params!.query!.end_date! < state.firstStart;
          return ok({
            assistants: [{ created_at: "2026-10-20T12:00:00Z", count: previous ? 6 : 3 }],
            sessions: [{ created_at: "2026-10-20T12:00:00Z", count: previous ? 6 : 12 }],
            questions: [{ created_at: "2026-10-20T12:00:00Z", count: previous ? 40123 : 40123 }]
          });
        case "/api/v1/token-usage/":
          return ok({
            total_token_usage: 1500,
            total_input_token_usage: 1200,
            total_output_token_usage: 300,
            models: []
          });
        case "/api/v1/analysis/assistant-activity/":
          return ok({
            active_assistant_count: 2,
            total_trackable_assistants: 3,
            active_user_count: 5
          });
        case "/api/v1/analysis/targets/": {
          const query = init!.params!.query! as unknown as Record<string, string | number>;
          const offset = Number(query.offset);
          const matching = TARGETS.filter(
            (item) =>
              (!query.q || item.name.toLowerCase().includes(String(query.q))) &&
              (query.activity !== "unused" || item.conversations.total === 0)
          );
          const compared = String(query.compare) === "true";
          // The listed targets that match, plus the personal spaces, which no filter narrows.
          const sum = (source: "total" | "user" | "widget" | "api_key") =>
            matching.reduce(
              (total, item) => total + item.conversations[source],
              PERSONAL.conversations[source]
            );
          return ok({
            items: matching.slice(offset, offset + Number(query.limit)),
            total_count: matching.length,
            limit: Number(query.limit),
            offset,
            personal: {
              ...PERSONAL,
              previous: compared ? { conversations: counts(30, 0, 0), questions: 60 } : null
            },
            totals: {
              conversations: {
                total: sum("total"),
                user: sum("user"),
                widget: sum("widget"),
                api_key: sum("api_key")
              },
              questions: matching.reduce(
                (total, item) => total + item.questions,
                PERSONAL.questions
              ),
              previous: compared ? { conversations: counts(1000, 400, 100), questions: 3000 } : null
            }
          });
        }
        default:
          throw new Error(`Unexpected GET ${path}`);
      }
    }
  }
}));
// recharts needs layout; the chart itself is not under test.
vi.mock("./usage-area-chart", () => ({ UsageAreaChart: () => <div>chart</div> }));

import { InsightsPage } from "./insights-page";

beforeEach(() => {
  state.aggregated = "pending";
  state.calls.length = 0;
  state.firstStart = "";
});
afterEach(cleanup);

/** The query of every request for the table of assistants and group chats. */
const targetsCalls = () =>
  state.calls.filter((call) => call.path === "/api/v1/analysis/targets/").map((call) => call.query);

const busyRegions = () =>
  screen.getAllByRole("status").filter((region) => region.getAttribute("aria-busy") === "true");

describe("InsightsPage", () => {
  it("formats period totals in the selected UI language", async () => {
    state.aggregated = "ok";
    renderInApp(
      <IntlProvider locale="en" messages={en}>
        <InsightsPage />
      </IntlProvider>
    );
    expect(await screen.findByText("40,123")).toBeTruthy();
  });

  it("compares period totals and uses the same precise bounds for tokens", async () => {
    state.aggregated = "ok";
    renderInApp(<InsightsPage />, {
      appContext: testAppContext({ permissions: ["insights", "admin"] })
    });
    await screen.findByText("chart");
    fireEvent.click(screen.getByRole("switch", { name: "Jämför" }));
    expect(await screen.findByText(/\+100.*jämfört med föregående period/)).toBeTruthy();
    expect(screen.getByText(/−50.*jämfört med föregående period/)).toBeTruthy();
    const aggregate = state.calls.find((call) => call.path.endsWith("aggregated/"))!.query;
    const tokens = state.calls.find((call) => call.path === "/api/v1/token-usage/")!.query;
    expect(aggregate).toMatchObject(tokens!);
    expect(aggregate!.time_zone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    expect(tokens!.end_date).toMatch(/\.999999Z$/);
    const usageLink = screen.getByRole("link", { name: "Visa tokenanvändning" });
    expect(usageLink.getAttribute("href")).toMatch(/tab=tokens&from=/);
    // A stand-alone link: a touch-sized row of its own (the contract measures it on the screen).
    expect(usageLink.className).toContain("pointer-coarse:min-h-11");
    expect(state.calls.some((call) => call.path === "/api/v1/analysis/counts/")).toBe(false);
  });

  it("does not request or link to admin token usage for an insights-only user", async () => {
    state.aggregated = "ok";
    renderInApp(<InsightsPage />, { appContext: testAppContext({ permissions: ["insights"] }) });
    await screen.findByText("chart");
    expect(state.calls.some((call) => call.path === "/api/v1/token-usage/")).toBe(false);
    expect(screen.queryByRole("link", { name: "Visa tokenanvändning" })).toBeNull();
  });

  it("shows a chart-sized skeleton while the usage series loads", async () => {
    renderInApp(<InsightsPage />);
    // The activity cards and list have loaded: the one busy region left is the chart's.
    await screen.findByText("Aktiva assistenter");
    await waitFor(() => expect(busyRegions()).toHaveLength(1));
    expect(screen.queryByText("chart")).toBeNull();
  });

  it("shows the shared error state in the chart area and retries", async () => {
    state.aggregated = "fail";
    renderInApp(<InsightsPage />);
    expect(await screen.findByText("Innehållet kunde inte hämtas")).toBeTruthy();

    state.aggregated = "ok";
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("chart")).toBeTruthy();
  });

  it("insets the usage card like the totals above it on a phone", async () => {
    state.aggregated = "ok";
    renderInApp(<InsightsPage />);
    const heading = await screen.findByRole("heading", { name: "Assistentanvändning" });
    // jsdom applies no CSS: the inset is asserted as its classes. At p-6 the card's text
    // sat 8 px further in than the totals' (p-4) above it.
    const card = heading.closest(".astryx-card");
    expect(card?.className.split(" ")).toContain("p-4");
    expect(card?.className).toContain("sm:p-6");
    // And the activity cards after it, so the three kinds of card share one inset.
    for (const label of ["Aktiva assistenter", "Aktiva användare"]) {
      const activity = (await screen.findByText(label)).closest(".astryx-card");
      expect(activity?.className.split(" ")).toContain("p-4");
    }
  });

  it("lists the assistants and group chats from the API, with their use and where to go", async () => {
    renderInApp(<InsightsPage />, { appContext: testAppContext({ permissions: ["insights"] }) });
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    expect(targetsCalls()[0]).toMatchObject({
      sort: "conversations",
      order: "desc",
      activity: "all",
      compare: false,
      offset: 0,
      limit: 25
    });
    expect(state.calls.some((call) => call.path === "/api/v1/analysis/metadata-statistics/")).toBe(
      false
    );
    const row = (name: string) =>
      within(table)
        .getAllByRole("row")
        .find((candidate) => within(candidate).queryByText(name))!;

    const assistant = row("Bygglovsassistenten");
    expect(
      within(assistant).getByRole("link", { name: "Bygglovsassistenten" }).getAttribute("href")
    ).toMatch(/^\/admin\/insights\/assistant\/t-1\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}$/);
    expect(
      within(assistant).getByRole("img", {
        name: /^58\s%\sanvändare, 36\s%\swidget, 6\s%\sAPI$/
      })
    ).toBeTruthy();
    expect(within(assistant).getByText(/^78\s%$/)).toBeTruthy();

    const groupChat = row("Upphandlingsstöd");
    expect(
      within(groupChat).getByRole("link", { name: "Upphandlingsstöd" }).getAttribute("href")
    ).toMatch(/^\/admin\/insights\/group-chat\/t-2\?/);
    expect(within(groupChat).getByText("Ekonomi, gruppchatt")).toBeTruthy();
    expect(within(groupChat).getByText("Inga betyg")).toBeTruthy();

    // Insights off: use only, and the way to the switch instead of the ratings.
    const off = row("Skolskjutsfrågor");
    expect(within(off).queryByRole("link", { name: "Skolskjutsfrågor" })).toBeNull();
    expect(within(off).getByText("Insikter är avstängda")).toBeTruthy();
    expect(
      within(off).getByRole("link", { name: "Öppna inställningen" }).getAttribute("href")
    ).toBe("/spaces/space-t-3/assistants/t-3/edit?section=publishing#publishing");
  });

  it("sorts, searches, filters and pages the table through the API", async () => {
    renderInApp(<InsightsPage />, { appContext: testAppContext({ permissions: ["insights"] }) });
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    expect(screen.getByText("Visar 25 av 27")).toBeTruthy();
    expect(
      within(table)
        .getByRole("columnheader", { name: /Konversationer/ })
        .getAttribute("aria-sort")
    ).toBe("descending");

    // Names start A to Z; a second click flips them.
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    await waitFor(() =>
      expect(targetsCalls().at(-1)).toMatchObject({ sort: "name", order: "asc", offset: 0 })
    );
    await waitFor(() =>
      expect(
        within(table).getByRole("columnheader", { name: /Namn/ }).getAttribute("aria-sort")
      ).toBe("ascending")
    );
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    await waitFor(() =>
      expect(targetsCalls().at(-1)).toMatchObject({ sort: "name", order: "desc" })
    );

    // "Visa fler" asks for the next offset and keeps the rows it has.
    fireEvent.click(await screen.findByRole("button", { name: "Visa fler" }));
    await waitFor(() => expect(targetsCalls().at(-1)).toMatchObject({ offset: 25 }));
    expect(await screen.findByText("Visar 27 av 27")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Visa fler" })).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "Oanvända" }));
    await waitFor(() =>
      expect(targetsCalls().at(-1)).toMatchObject({ activity: "unused", offset: 0 })
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Sök assistent eller gruppchatt" }), {
      target: { value: "  oanvänd 2  " }
    });
    await waitFor(() => expect(targetsCalls().at(-1)).toMatchObject({ q: "oanvänd 2" }));
    expect(await screen.findByText("Visar 6 av 6")).toBeTruthy();
  });

  it("compares each target's conversations when Jämför is on", async () => {
    renderInApp(<InsightsPage />, { appContext: testAppContext({ permissions: ["insights"] }) });
    await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    fireEvent.click(screen.getByRole("switch", { name: "Jämför" }));
    await waitFor(() => expect(targetsCalls().at(-1)).toMatchObject({ compare: true }));
    // The organisation's conversations against 1 500, and the personal spaces' against 30.
    expect(await screen.findByText(/^\+36\s%/)).toBeTruthy();
    const table = screen.getByRole("table", { name: "Assistenter och gruppchattar" });
    expect(within(within(table).getAllByRole("row")[1]!).getByText(/^\+40\s%/)).toBeTruthy();
  });

  it("shows the personal spaces as one first row and the organisation's total, only unfiltered", async () => {
    renderInApp(<InsightsPage />, { appContext: testAppContext({ permissions: ["insights"] }) });
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    // Conversations by source in words that count conversations: listed targets and personal spaces.
    const totals =
      "Konversationer i perioden: 2 037, varav 1 424 från användare, 537 via widget och 76 via API";
    expect(screen.getByText(totals)).toBeTruthy();
    const firstRow = () => within(table).getAllByRole("row")[1]!;
    const cells = () =>
      within(firstRow())
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    // Told apart as a summary for assistive technology, and never a link to someone's assistant.
    expect(cells()).toEqual([
      "Personliga assistenter sammanlagt3 assistenter i personliga utrymmen",
      "42",
      "",
      "90",
      "Visas inte för personliga assistenter"
    ]);
    expect(
      within(firstRow()).getByRole("img", { name: /^95\s%\sanvändare, 5\s%\sAPI$/ })
    ).toBeTruthy();
    expect(within(firstRow()).queryByRole("link")).toBeNull();
    // It stays first whatever the sort, and is not counted among the listed targets.
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    await waitFor(() => expect(targetsCalls().at(-1)).toMatchObject({ sort: "name" }));
    expect(cells()[0]).toMatch(/^Personliga assistenter/);
    expect(screen.getByText("Visar 25 av 27")).toBeTruthy();

    // A search or "Oanvända" lists some targets: no personal row, no organisation total.
    const search = screen.getByRole("textbox", { name: "Sök assistent eller gruppchatt" });
    fireEvent.change(search, { target: { value: "bygg" } });
    expect(screen.queryByText(/^Konversationer i perioden/)).toBeNull();
    await waitFor(() => expect(targetsCalls().at(-1)).toMatchObject({ q: "bygg" }));
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(2));
    expect(within(table).queryByText("Personliga assistenter")).toBeNull();
    expect(screen.queryByText(/^Konversationer i perioden/)).toBeNull();

    fireEvent.change(search, { target: { value: "" } });
    expect(await screen.findByText(totals)).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Oanvända" }));
    expect(screen.queryByText(/^Konversationer i perioden/)).toBeNull();
    await waitFor(() => expect(targetsCalls().at(-1)).toMatchObject({ activity: "unused" }));
    expect(await screen.findByText("Visar 24 av 24")).toBeTruthy();
    expect(screen.queryByText("Personliga assistenter")).toBeNull();
    expect(screen.queryByText(/^Konversationer i perioden/)).toBeNull();
  });
});
