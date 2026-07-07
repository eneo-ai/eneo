import { describe, expect, it } from "vitest";
import { fileRestrictionsRules, inputFieldRules, planFileUploads } from "./upload-plan";

describe("inputFieldRules", () => {
  it("derives accept string, caps and per-type limits", () => {
    const rules = inputFieldRules({
      accepted_file_types: [
        { mimetype: "application/pdf", size_limit: 1000 },
        { mimetype: "text/plain", size_limit: 500 }
      ],
      limit: { max_files: 3, max_size: 5000 }
    });
    expect(rules.acceptString).toBe("application/pdf,text/plain");
    expect(rules.maxFiles).toBe(3);
    expect(rules.maxSize).toBe(5000);
    expect(rules.perTypeLimits).toEqual([
      { mimetype: "application/pdf", sizeLimit: 1000 },
      { mimetype: "text/plain", sizeLimit: 500 }
    ]);
  });

  it("treats zero input-field limits as unbounded", () => {
    const rules = inputFieldRules({
      accepted_file_types: [],
      limit: { max_files: 0, max_size: 0 }
    });
    expect(rules.acceptString).toBe("");
    expect(rules.maxFiles).toBe(Infinity);
    expect(rules.maxSize).toBe(Infinity);
  });
});

describe("fileRestrictionsRules", () => {
  it("preserves zero resource limits so uploads can be disabled", () => {
    const rules = fileRestrictionsRules({
      accepted_file_types: [],
      limit: { max_files: 0, max_size: 0 }
    });
    expect(rules.maxFiles).toBe(0);
    expect(rules.maxSize).toBe(0);
  });
});

describe("planFileUploads", () => {
  const rules = inputFieldRules({
    accepted_file_types: [
      { mimetype: "application/pdf", size_limit: 1000 },
      { mimetype: "text/plain", size_limit: 500 }
    ],
    limit: { max_files: 3, max_size: 1800 }
  });

  it("accepts only files that fit type, count, per-type and total limits", () => {
    const plan = planFileUploads(
      [
        { name: "a.pdf", type: "application/pdf", size: 900 },
        { name: "too-large.txt", type: "text/plain", size: 600 },
        { name: "b.pdf", type: "application/pdf", size: 700 },
        { name: "unsupported.png", type: "image/png", size: 10 },
        { name: "over-total.pdf", type: "application/pdf", size: 300 }
      ],
      [],
      rules
    );

    expect(plan.accepted.map((file) => file.name)).toEqual(["a.pdf", "b.pdf"]);
    expect(plan.rejected.map((rejection) => [rejection.file.name, rejection.reason])).toEqual([
      ["too-large.txt", "too-large"],
      ["unsupported.png", "unsupported-type"],
      ["over-total.pdf", "max-total-size"]
    ]);
  });

  it("counts existing files when enforcing max files", () => {
    const plan = planFileUploads(
      [
        { name: "b.pdf", type: "application/pdf", size: 200 },
        { name: "c.pdf", type: "application/pdf", size: 200 }
      ],
      [{ size: 100 }, { size: 100 }],
      rules
    );

    expect(plan.accepted.map((file) => file.name)).toEqual(["b.pdf"]);
    expect(plan.rejected).toEqual([
      { file: { name: "c.pdf", type: "application/pdf", size: 200 }, reason: "max-files", limit: 3 }
    ]);
  });
});
