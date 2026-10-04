import { afterEach, describe, expect, it } from "vitest";
import { withLocale } from "$lib/features/flows/testLocale";
import { auditActorEmail, auditActorLabel } from "./audit-actor-label";

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("auditActorLabel", () => {
  it("shows the recorded name, and names a nameless recorded actor by its kind", () => {
    restore = withLocale("en");
    const user = { actor: { type: "user", id: "u1", name: "Maria", email: "m@example.org" } };

    expect(auditActorLabel(user)).toBe("Maria");
    expect(auditActorEmail(user)).toBe("m@example.org");
    expect(auditActorLabel({ actor: { type: "user", id: "u1" } })).toBe("Deleted user");
    expect(auditActorLabel({ actor: { type: "service_key", id: "k1" } })).toBe("Deleted key");
    expect(auditActorLabel({ actor: { type: "service_principal", id: "s1" } })).toBe("Deleted key");
    expect(auditActorLabel({ actor: { id: "u2" } })).toBe("u2");
    expect(auditActorLabel({ actor: { type: "system", via: "operator_redrive" } })).toBe("System");
    expect(auditActorLabel({})).toBe("System");
    expect(auditActorLabel({ actor: null })).toBe("System");
    expect(auditActorEmail({ actor: "text" })).toBeUndefined();
  });

  it("uses Swedish labels", () => {
    restore = withLocale("sv");

    expect(auditActorLabel({ actor: { type: "user", id: "u1" } })).toBe("Raderad användare");
    expect(auditActorLabel({ actor: { type: "service_key", id: "k1" } })).toBe("Raderad nyckel");
  });
});
