// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { Widget } from "./autosave";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { WidgetUsage } from "./widget-usage";

// West of UTC: the day the API names must not slip to the day before.
const previousZone = process.env.TZ;
beforeAll(() => {
  process.env.TZ = "America/New_York";
});
afterAll(() => {
  process.env.TZ = previousZone;
});

it("labels each row with the calendar day the API sent", async () => {
  api.GET.mockResolvedValue({
    data: {
      days: [
        {
          day: "2026-11-04",
          questions: 3,
          input_tokens: 120,
          output_tokens: 40,
          blocked_budget: 0,
          blocked_rate: 0,
          helpful: 1,
          unhelpful: 0
        }
      ],
      budget_used_today: 0,
      daily_token_budget: 500000
    },
    response: new Response("{}")
  });
  renderInApp(
    <WidgetUsage
      widget={
        {
          id: "w1",
          limits: { daily_token_budget: 500000 },
          updated_at: "2026-11-04T08:00:00Z"
        } as unknown as Widget
      }
    />
  );
  const expected = new Intl.DateTimeFormat("sv-SE", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC"
  }).format(new Date("2026-11-04"));
  expect(expected).toContain("4");
  expect(await screen.findByText(expected)).toBeTruthy();
});
