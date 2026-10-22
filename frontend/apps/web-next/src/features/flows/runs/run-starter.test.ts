import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { makeRunSummary } from "./run-fixtures";
import { startedByUser, starterName } from "./run-starter";

const t = (key: string) => (messages as Record<string, string>)[key] ?? key;

const serviceKey = {
  principal_type: "service_key" as const,
  id: "service-1",
  display_name: "Ärendeintag",
  email: null
};

describe("starterName", () => {
  it("names the person or service key that started the run", () => {
    expect(starterName(makeRunSummary(), t)).toBe("Anna Lind");
    expect(starterName(makeRunSummary({ started_by: serviceKey }), t)).toBe("Ärendeintag");
  });

  it("says what kind of principal it was when no name is known", () => {
    expect(starterName(makeRunSummary({ started_by: null }), t)).toBe(
      messages.flow_runs_started_by_person
    );
    expect(
      starterName(makeRunSummary({ started_by: { ...serviceKey, display_name: null } }), t)
    ).toBe(messages.flow_runs_started_by_service_key);
    expect(
      starterName(makeRunSummary({ principal_type: "service_key", started_by: undefined }), t)
    ).toBe(messages.flow_runs_started_by_service_key);
  });
});

describe("startedByUser", () => {
  it("is true only for the signed-in person's own runs", () => {
    expect(startedByUser(makeRunSummary(), "user-1")).toBe(true);
    expect(startedByUser(makeRunSummary(), "user-2")).toBe(false);
    expect(startedByUser(makeRunSummary({ started_by: serviceKey }), "service-1")).toBe(false);
  });

  it("does not guess when the run does not say who started it", () => {
    expect(startedByUser(makeRunSummary({ started_by: null }), "user-1")).toBeNull();
  });
});
