import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { fieldBounds } from "./flow-settings";
import { flowSettingsFixture } from "./flow-settings-fixtures";
import {
  formatSeconds,
  problemMessage,
  refusalMessage,
  type Translate
} from "./flow-settings-format";

const catalog: Record<string, string> = {
  flow_admin_problem_range: "between {min} and {max}",
  flow_admin_duration_seconds: "{seconds} s",
  flow_admin_duration_minutes: "{minutes} min",
  flow_admin_duration_hours: "{hours} h {minutes} min",
  flow_error_max_concurrent_runs_exceeds_server_capacity: "over capacity"
};
const t = Object.assign(
  (key: string, values: Record<string, string | number> = {}) =>
    (catalog[key] ?? key).replace(/\{(\w+)\}/g, (_, name: string) => String(values[name])),
  { has: (key: string) => key in catalog }
) satisfies Translate;

describe("problemMessage", () => {
  it("states a range in the units the field shows", () => {
    const bounds = fieldBounds(flowSettingsFixture());

    expect(
      problemMessage(
        { kind: "range", min: 1024, max: 65_536 },
        bounds.max_recorded_passage_bytes,
        t,
        "sv"
      )
    ).toBe("between 1 and 64");
    expect(
      problemMessage(
        { kind: "range", min: 60, max: 14_400 },
        bounds.audio_max_duration_seconds,
        t,
        "sv"
      )
    ).toBe("between 1 and 240");
  });
});

describe("formatSeconds", () => {
  it("says time in whole units", () => {
    expect(formatSeconds(45, t)).toBe("45 s");
    expect(formatSeconds(1200, t)).toBe("20 min");
    expect(formatSeconds(28_740, t)).toBe("7 h 59 min");
  });
});

describe("refusalMessage", () => {
  it("prefers the flow error catalog's wording for the refusal's code", () => {
    const error = new EneoApiError("max_concurrent_runs exceeds the server capacity.", {
      status: 400,
      reason: "max_concurrent_runs_exceeds_server_capacity"
    });
    expect(refusalMessage(error, t)).toBe("over capacity");
    expect(refusalMessage(new EneoApiError("Nope", { status: 400, reason: "other" }), t)).toBe(
      "Nope"
    );
  });
});
