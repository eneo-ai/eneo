import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const listFlowRetentionHolds = vi.hoisted(() => vi.fn());
const placeFlowRetentionHold = vi.hoisted(() => vi.fn());
const releaseFlowRetentionHold = vi.hoisted(() => vi.fn());
const extendFlowRetentionHoldReview = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastErrorMock = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    settings: {
      listFlowRetentionHolds,
      placeFlowRetentionHold,
      releaseFlowRetentionHold,
      extendFlowRetentionHoldReview
    }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { success: toastSuccess, error: vi.fn() }
}));

vi.mock("$lib/core/errors", () => ({
  toastError: toastErrorMock
}));

vi.mock("$lib/paraglide/messages", async () => {
  const { default: swedishMessages } = await import("../../../../../messages/sv.json");

  return {
    m: new Proxy<Record<string, unknown>>(
      {},
      {
        get: (_target, key) => {
          const label = String(key);
          return (params?: Record<string, unknown>) => {
            const template = (swedishMessages as Record<string, string>)[label];
            if (typeof template !== "string") {
              return params ? `${label} ${JSON.stringify(params)}` : label;
            }
            return template.replace(/\{(\w+)\}/g, (_match, name: string) =>
              String(params?.[name] ?? `{${name}}`)
            );
          };
        }
      }
    )
  };
});

vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv"
}));

import FlowRetentionHoldsSection from "./FlowRetentionHoldsSection.svelte";
import { addLocalDays, endOfLocalDay, localDate } from "./flowRetentionHold";

const RUN_ID = "3f2c7a4e-1b2d-4c3e-8f9a-0b1c2d3e4f5a";
const FLOW = { id: "flow-1", name: "Ärendeflöde" };
const TODAY = localDate(new Date());

function hold(overrides: Record<string, unknown> = {}) {
  return {
    id: "hold-1",
    flow_id: FLOW.id,
    flow_name: FLOW.name,
    flow_retired: false,
    space_id: "space-1",
    flow_run_id: null,
    reason: "Begäran om utlämnande 2026-114",
    review_by: endOfLocalDay(addLocalDays(TODAY, 30)),
    review_overdue: false,
    ends_at: null,
    created_at: "2026-10-01T08:00:00Z",
    created_by: { type: "user", id: "user-1", name: "Anna Admin" },
    released_at: null,
    released_by: null,
    release_reason: null,
    active: true,
    scope: "flow",
    ...overrides
  };
}

function renderSection(
  props: Partial<{
    initialHolds: unknown;
    maxReviewDays: number | null;
    selectedFlow: { id: string; name: string } | null;
    onHoldsChanged: () => void;
  }> = {}
) {
  return render(FlowRetentionHoldsSection, {
    initialHolds: { items: [], has_more: false, review_limit_days: 365 },
    maxReviewDays: 365,
    selectedFlow: FLOW,
    ...props
  } as never);
}

async function openPlaceDialog() {
  await page.getByRole("button", { name: "Lägg spärr på Ärendeflöde" }).click();
  return page.getByRole("dialog");
}

describe("legal holds section", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listFlowRetentionHolds.mockResolvedValue({
      items: [],
      has_more: false,
      review_limit_days: 365
    });
  });

  test("lists who placed each hold, why, when it is reviewed and ends", async () => {
    renderSection({
      initialHolds: {
        items: [
          hold(),
          hold({
            id: "hold-2",
            flow_run_id: RUN_ID,
            scope: "run",
            review_overdue: true,
            ends_at: "2026-12-31T22:59:59Z",
            created_by: null
          })
        ],
        has_more: false,
        review_limit_days: 365
      }
    });

    await expect.element(page.getByText("Hela flödet, även kommande körningar")).toBeVisible();
    await expect.element(page.getByText(`Körning ${RUN_ID}`)).toBeVisible();
    await expect.element(page.getByText("Anna Admin")).toBeVisible();
    await expect.element(page.getByText("Okänd")).toBeVisible();
    await expect.element(page.getByText("Tills den hävs", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Omprövning försenad")).toBeVisible();
    await expect.element(page.getByText("Begäran om utlämnande 2026-114").first()).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: `Häv spärren: Körning ${RUN_ID}` }))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: `Flytta omprövningen: Körning ${RUN_ID}` }))
      .toBeVisible();
  });

  test("the history view keeps released and ended holds with who and why", async () => {
    listFlowRetentionHolds.mockResolvedValue({
      items: [
        hold({
          id: "released",
          active: false,
          released_at: "2026-10-02T09:00:00Z",
          released_by: { type: "user", id: "user-2", name: "Bo Registrator" },
          release_reason: "Begäran besvarad"
        }),
        hold({ id: "ended", active: false, ends_at: "2026-10-03T21:59:59Z" })
      ],
      has_more: false,
      review_limit_days: 365
    });
    renderSection({ initialHolds: { items: [], has_more: false, review_limit_days: 365 } });

    await page.getByRole("radio", { name: "Alla, även avslutade" }).click();

    await vi.waitFor(() =>
      expect(listFlowRetentionHolds).toHaveBeenCalledWith({ status: "all", limit: 200, offset: 0 })
    );
    await expect.element(page.getByText("Hävd", { exact: true })).toBeVisible();
    await expect.element(page.getByText(/Av Bo Registrator/)).toBeVisible();
    await expect.element(page.getByText("Begäran besvarad")).toBeVisible();
    await expect.element(page.getByText("Slutdatum passerat")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: /^Häv spärren/ }))
      .not.toBeInTheDocument();
  });

  test("says when nothing is held and when the list could not load", async () => {
    const { unmount } = renderSection();
    await expect.element(page.getByText("Inga aktiva spärrar")).toBeVisible();
    unmount();

    renderSection({ initialHolds: null });
    await expect.element(page.getByText("Spärrarna kunde inte hämtas")).toBeVisible();
  });

  test("placing a hold needs a chosen flow", async () => {
    renderSection({ selectedFlow: null });

    await expect.element(page.getByRole("button", { name: "Lägg spärr" })).toBeDisabled();
    await expect
      .element(page.getByText("Välj ett flöde ovan för att lägga en spärr."))
      .toBeVisible();
  });

  test("a hold needs a reason and a review date before it is placed", async () => {
    // Midday, no daylight-saving change within the limit: day 89 always ends
    // inside it (across a change the last offered day moves; see latestReviewDate).
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date(2026, 4, 12, 12, 0));
      const today = localDate(new Date());
      const onHoldsChanged = vi.fn();
      placeFlowRetentionHold.mockResolvedValue({ holds: [hold()] });
      listFlowRetentionHolds.mockResolvedValue({
        items: [hold()],
        has_more: false,
        review_limit_days: 365
      });
      renderSection({ onHoldsChanged, maxReviewDays: 90 });

      const dialog = await openPlaceDialog();
      await expect.element(dialog.getByText("Ärendeflöde")).toBeVisible();
      await dialog.getByRole("button", { name: "Lägg spärr" }).click();
      await expect.element(dialog.getByText("Ange ett skäl på 1–512 tecken.")).toBeVisible();
      await expect
        .element(dialog.getByText("Välj ett datum från i dag och högst 90 dagar fram."))
        .toBeVisible();
      expect(placeFlowRetentionHold).not.toHaveBeenCalled();

      await dialog.getByRole("textbox", { name: "Skäl" }).fill("  Begäran om utlämnande  ");
      await dialog.getByLabelText("Omprövas senast").fill(addLocalDays(today, 90));
      await dialog.getByRole("button", { name: "Lägg spärr" }).click();
      await expect
        .element(dialog.getByText("Välj ett datum från i dag och högst 90 dagar fram."))
        .toBeVisible();
      expect(placeFlowRetentionHold).not.toHaveBeenCalled();

      const review = addLocalDays(today, 89);
      await dialog.getByLabelText("Omprövas senast").fill(review);
      await dialog.getByRole("button", { name: "Lägg spärr" }).click();

      await vi.waitFor(() =>
        expect(placeFlowRetentionHold).toHaveBeenCalledExactlyOnceWith({
          flowId: "flow-1",
          runIds: null,
          reason: "Begäran om utlämnande",
          reviewBy: endOfLocalDay(review),
          endsAt: null
        })
      );
      await vi.waitFor(() => expect(onHoldsChanged).toHaveBeenCalledOnce());
      expect(listFlowRetentionHolds).toHaveBeenCalledWith({
        status: "active",
        limit: 200,
        offset: 0
      });
      expect(toastSuccess).toHaveBeenCalledWith("Spärren är lagd.");
      await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  test("holds named runs until the end of the chosen day", async () => {
    placeFlowRetentionHold.mockResolvedValue({ holds: [] });
    renderSection();

    const dialog = await openPlaceDialog();
    await dialog.getByRole("radio", { name: "Utvalda körningar" }).click();
    await dialog.getByRole("textbox", { name: "Körnings-ID" }).fill("not-a-run");
    await dialog.getByRole("textbox", { name: "Skäl" }).fill("Tillsyn");
    await dialog.getByLabelText("Omprövas senast").fill(addLocalDays(TODAY, 30));
    await dialog.getByRole("button", { name: "Lägg spärr" }).click();
    await expect
      .element(dialog.getByText("Ange 1–100 giltiga körnings-id, ett per rad."))
      .toBeVisible();
    expect(placeFlowRetentionHold).not.toHaveBeenCalled();

    await dialog.getByRole("textbox", { name: "Körnings-ID" }).fill(`${RUN_ID}\n${RUN_ID}`);
    await dialog.getByLabelText("Slutdatum (valfritt)").fill("2099-03-31");
    await dialog.getByRole("button", { name: "Lägg spärr" }).click();

    await vi.waitFor(() =>
      expect(placeFlowRetentionHold).toHaveBeenCalledExactlyOnceWith({
        flowId: "flow-1",
        runIds: [RUN_ID, RUN_ID],
        reason: "Tillsyn",
        reviewBy: endOfLocalDay(addLocalDays(TODAY, 30)),
        endsAt: new Date(2099, 2, 31, 23, 59, 59, 999).toISOString()
      })
    );
  });

  test("shows a typed refusal inside the dialog", async () => {
    placeFlowRetentionHold.mockRejectedValue({
      status: 400,
      code: 9001,
      response: { code: "flow_retention_hold_run_not_in_flow" }
    });
    renderSection();

    const dialog = await openPlaceDialog();
    await dialog.getByRole("radio", { name: "Utvalda körningar" }).click();
    await dialog.getByRole("textbox", { name: "Körnings-ID" }).fill(RUN_ID);
    await dialog.getByRole("textbox", { name: "Skäl" }).fill("Tillsyn");
    await dialog.getByLabelText("Omprövas senast").fill(addLocalDays(TODAY, 30));
    await dialog.getByRole("button", { name: "Lägg spärr" }).click();

    await expect
      .element(dialog.getByText("Minst en körning tillhör inte flödet. Kontrollera id:na."))
      .toBeVisible();
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  test("releasing asks for a reason and explains what becomes deletable", async () => {
    const onHoldsChanged = vi.fn();
    releaseFlowRetentionHold.mockResolvedValue(hold({ active: false }));
    renderSection({
      initialHolds: { items: [hold()], has_more: false, review_limit_days: 365 },
      onHoldsChanged
    });

    await page
      .getByRole("button", { name: "Häv spärren: Hela flödet, även kommande körningar" })
      .click();
    const dialog = page.getByRole("alertdialog");
    await expect
      .element(dialog.getByText(/följer sin gallringspolicy igen och kan gallras/))
      .toBeVisible();
    await dialog.getByRole("button", { name: "Häv spärren" }).click();
    await expect.element(dialog.getByText("Ange ett skäl på 1–512 tecken.")).toBeVisible();
    expect(releaseFlowRetentionHold).not.toHaveBeenCalled();

    await dialog.getByRole("textbox", { name: "Skäl till hävning" }).fill("Begäran besvarad");
    await dialog.getByRole("button", { name: "Häv spärren" }).click();

    await vi.waitFor(() =>
      expect(releaseFlowRetentionHold).toHaveBeenCalledExactlyOnceWith({
        holdId: "hold-1",
        reason: "Begäran besvarad"
      })
    );
    await vi.waitFor(() => expect(onHoldsChanged).toHaveBeenCalledOnce());
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    await expect.element(page.getByText("Inga aktiva spärrar")).toBeVisible();
  });

  test("moving the review needs a later date and a reason", async () => {
    const current = addLocalDays(TODAY, 10);
    extendFlowRetentionHoldReview.mockResolvedValue(hold());
    renderSection({
      initialHolds: {
        items: [hold({ review_by: endOfLocalDay(current), review_overdue: false })],
        has_more: false,
        review_limit_days: 365
      }
    });

    await page
      .getByRole("button", { name: "Flytta omprövningen: Hela flödet, även kommande körningar" })
      .click();
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog.getByText(/Spärren fortsätter att stoppa gallring/)).toBeVisible();
    await dialog.getByLabelText("Nytt omprövningsdatum").fill(current);
    await dialog.getByRole("button", { name: "Flytta omprövning" }).click();
    await expect
      .element(dialog.getByText("Välj ett datum efter det nuvarande, högst 365 dagar fram."))
      .toBeVisible();
    await expect.element(dialog.getByText("Ange ett skäl på 1–512 tecken.")).toBeVisible();
    expect(extendFlowRetentionHoldReview).not.toHaveBeenCalled();

    const next = addLocalDays(current, 60);
    await dialog.getByLabelText("Nytt omprövningsdatum").fill(next);
    await dialog.getByRole("textbox", { name: "Varför spärren behövs" }).fill("Fortfarande öppen");
    await dialog.getByRole("button", { name: "Flytta omprövning" }).click();

    await vi.waitFor(() =>
      expect(extendFlowRetentionHoldReview).toHaveBeenCalledExactlyOnceWith({
        holdId: "hold-1",
        reviewBy: endOfLocalDay(next),
        reason: "Fortfarande öppen"
      })
    );
    expect(toastSuccess).toHaveBeenCalledWith("Omprövningsdatumet är flyttat.");
  });

  test("an already released hold is reported inside the release dialog", async () => {
    releaseFlowRetentionHold.mockRejectedValue({
      status: 409,
      code: 9002,
      response: { code: "flow_retention_hold_already_released" }
    });
    renderSection({ initialHolds: { items: [hold()], has_more: false, review_limit_days: 365 } });

    await page
      .getByRole("button", { name: "Häv spärren: Hela flödet, även kommande körningar" })
      .click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox", { name: "Skäl till hävning" }).fill("Klar");
    await dialog.getByRole("button", { name: "Häv spärren" }).click();

    await expect.element(dialog.getByText("Spärren är redan hävd.")).toBeVisible();
    // The list is out of date: it is read again.
    await vi.waitFor(() =>
      expect(listFlowRetentionHolds).toHaveBeenCalledWith({
        status: "active",
        limit: 200,
        offset: 0
      })
    );
  });

  test("a dialog offers dates from the day it is opened", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date(2026, 9, 10, 12, 0));
      renderSection({ maxReviewDays: 30 });

      let dialog = await openPlaceDialog();
      const review = () => dialog.getByLabelText("Omprövas senast");
      await expect.element(review()).toHaveAttribute("min", "2026-10-10");
      await expect.element(review()).toHaveAttribute("max", "2026-11-08");
      await dialog.getByRole("button", { name: "Avbryt" }).click();
      await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();

      vi.setSystemTime(new Date(2026, 9, 12, 12, 0));
      dialog = await openPlaceDialog();
      await expect.element(review()).toHaveAttribute("min", "2026-10-12");
      await expect.element(review()).toHaveAttribute("max", "2026-11-10");
    } finally {
      vi.useRealTimers();
    }
  });

  test("without a readable review limit no hold can be placed or reviewed", async () => {
    renderSection({
      maxReviewDays: null,
      initialHolds: { items: [hold()], has_more: false, review_limit_days: 365 }
    });

    await expect
      .element(page.getByText(/Den längsta tiden till omprövning kunde inte hämtas/))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "Lägg spärr på Ärendeflöde" }))
      .toBeDisabled();
    await expect
      .element(
        page.getByRole("button", {
          name: "Flytta omprövningen: Hela flödet, även kommande körningar"
        })
      )
      .toBeDisabled();
  });

  test("pages through more than 200 holds so every one can be reached", async () => {
    const pageOf = (start: number, count: number) =>
      Array.from({ length: count }, (_, index) =>
        hold({ id: `hold-${start + index}`, flow_name: `Flöde ${start + index}` })
      );
    listFlowRetentionHolds.mockImplementation(async ({ offset }: { offset: number }) =>
      offset === 0
        ? { items: pageOf(0, 200), has_more: true, review_limit_days: 365 }
        : { items: pageOf(200, 5), has_more: false, review_limit_days: 365 }
    );
    renderSection({
      initialHolds: { items: pageOf(0, 200), has_more: true, review_limit_days: 365 }
    });

    await expect.element(page.getByText("Visar 1–200")).toBeVisible();
    await expect.element(page.getByRole("button", { name: "Föregående" })).toBeDisabled();
    await page.getByRole("button", { name: "Nästa" }).click();

    await expect.element(page.getByText("Visar 201–205")).toBeVisible();
    await expect.element(page.getByText("Flöde 204")).toBeVisible();
    expect(listFlowRetentionHolds).toHaveBeenLastCalledWith({
      status: "active",
      limit: 200,
      offset: 200
    });
    await expect.element(page.getByRole("button", { name: "Nästa" })).toBeDisabled();
    await page.getByRole("button", { name: "Föregående" }).click();
    await expect.element(page.getByText("Visar 1–200")).toBeVisible();
  });

  test("releasing the last hold on the last page returns to the previous page", async () => {
    const pageOf = (start: number, count: number) =>
      Array.from({ length: count }, (_, index) =>
        hold({ id: `hold-${start + index}`, flow_name: `Flöde ${start + index}` })
      );
    let released = false;
    listFlowRetentionHolds.mockImplementation(async ({ offset }: { offset: number }) => {
      if (offset === 0) return { items: pageOf(0, 200), has_more: true, review_limit_days: 365 };
      if (offset === 200) {
        return { items: pageOf(200, 200), has_more: !released, review_limit_days: 365 };
      }
      return { items: released ? [] : pageOf(400, 1), has_more: false, review_limit_days: 365 };
    });
    releaseFlowRetentionHold.mockImplementation(async () => {
      released = true;
      return hold({ id: "hold-400", active: false });
    });
    renderSection({
      initialHolds: { items: pageOf(0, 200), has_more: true, review_limit_days: 365 }
    });

    await page.getByRole("button", { name: "Nästa" }).click();
    await expect.element(page.getByText("Visar 201–400")).toBeVisible();
    await page.getByRole("button", { name: "Nästa" }).click();
    await expect.element(page.getByText("Visar 401–401")).toBeVisible();
    await page.getByRole("button", { name: /^Häv spärren/ }).click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox", { name: "Skäl till hävning" }).fill("Besvarad");
    await dialog.getByRole("button", { name: "Häv spärren" }).click();

    // The emptied page is left for the previous one; paging still works.
    await expect.element(page.getByText("Visar 201–400")).toBeVisible();
    await expect.element(page.getByText("Flöde 399", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Inga aktiva spärrar")).not.toBeInTheDocument();
    expect(listFlowRetentionHolds).toHaveBeenLastCalledWith({
      status: "active",
      limit: 200,
      offset: 200
    });
    await expect.element(page.getByRole("button", { name: "Nästa" })).toBeDisabled();
    await page.getByRole("button", { name: "Föregående" }).click();
    await expect.element(page.getByText("Visar 1–200")).toBeVisible();
  });

  test("an empty first page still says the organization has no holds", async () => {
    listFlowRetentionHolds.mockResolvedValue({
      items: [],
      has_more: false,
      review_limit_days: 365
    });
    renderSection({ initialHolds: { items: [hold()], has_more: false, review_limit_days: 365 } });

    await page.getByRole("button", { name: "Uppdatera" }).click();
    await expect.element(page.getByText("Inga aktiva spärrar")).toBeVisible();
    expect(listFlowRetentionHolds).toHaveBeenCalledTimes(1);
  });

  test("a reload asked for during a reload runs after it, with the newest view", async () => {
    let finishFirst: (value: unknown) => void = () => undefined;
    listFlowRetentionHolds
      .mockImplementationOnce(() => new Promise((resolve) => (finishFirst = resolve)))
      .mockResolvedValue({ items: [], has_more: false, review_limit_days: 365 });
    renderSection({ initialHolds: { items: [hold()], has_more: false, review_limit_days: 365 } });

    await page.getByRole("button", { name: "Uppdatera" }).click();
    await page.getByRole("radio", { name: "Alla, även avslutade" }).click();
    finishFirst({ items: [hold()], has_more: false, review_limit_days: 365 });

    await vi.waitFor(() =>
      expect(listFlowRetentionHolds.mock.calls).toEqual([
        [{ status: "active", limit: 200, offset: 0 }],
        [{ status: "all", limit: 200, offset: 0 }]
      ])
    );
    await expect.element(page.getByText("Inga spärrar har lagts")).toBeVisible();
  });

  test("explains when the current review date is already beyond a lowered limit", async () => {
    const farAway = addLocalDays(TODAY, 300);
    renderSection({
      maxReviewDays: 90,
      initialHolds: {
        items: [hold({ review_by: endOfLocalDay(farAway) })],
        has_more: false,
        review_limit_days: 90
      }
    });

    await page
      .getByRole("button", { name: "Flytta omprövningen: Hela flödet, även kommande körningar" })
      .click();
    const dialog = page.getByRole("alertdialog");
    await expect
      .element(
        dialog.getByText(/ligger redan längre fram än den längsta tillåtna tiden \(90 dagar\)/)
      )
      .toBeVisible();
    await expect.element(dialog.getByRole("button", { name: "Flytta omprövning" })).toBeDisabled();
    expect(extendFlowRetentionHoldReview).not.toHaveBeenCalled();
  });
});
