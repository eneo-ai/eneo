import type { IntegrationKnowledge } from "../knowledge";
import { describe, expect, it } from "vitest";
import { createTranslator } from "use-intl";
import sv from "@/lib/i18n/messages/sv.json";
import { buildSourceProblems, isCredentialsError, type SkippedDocuments } from "./source-problems";
import type { SkipReasonCode } from "./skip-reasons";

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

type Metadata = NonNullable<IntegrationKnowledge["metadata"]>;

function item(id: string, metadata: Partial<Metadata> = {}): IntegrationKnowledge {
  return {
    id,
    name: id,
    metadata: { size: 0, last_sync_status: "success", ...metadata }
  } as IntegrationKnowledge;
}

function skipped(
  entries: [string, SkipReasonCode][],
  extra: Partial<SkippedDocuments> = {}
): SkippedDocuments {
  return {
    items: entries.map(([file, code]) => ({ file, reason: "", code, params: {}, retry: false })),
    total: entries.length,
    truncated: false,
    synced_at: null,
    ...extra
  };
}

const CREDENTIALS =
  "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";

describe("isCredentialsError", () => {
  it.each([
    [CREDENTIALS, true],
    [`  ${CREDENTIALS}`, true],
    ["Graph timeout", false],
    [null, false]
  ])("%s → %s", (message, expected) => {
    expect(isCredentialsError(message)).toBe(expected);
  });
});

describe("buildSourceProblems", () => {
  it("groups skipped files by cause, fixable before intentional, in a stable order", () => {
    const a = item("a");
    const b = item("b");
    const problems = buildSourceProblems(
      [a, b],
      {
        a: skipped([
          ["bild.png", "unsupported_type"],
          ["scan.pdf", "no_text_layer"],
          ["stor.pdf", "file_too_large"]
        ]),
        b: skipped([
          ["gammal.pdf", "no_text_layer"],
          ["hemlig.docx", "password_protected"],
          ["avbruten.pdf", "incomplete_download"]
        ])
      },
      t
    );

    expect(
      problems.fixable.map((group) => [group.category, group.files.map((f) => f.file)])
    ).toEqual([
      ["no_text_layer", ["scan.pdf", "gammal.pdf"]],
      ["too_large", ["stor.pdf"]],
      ["password_protected", ["hemlig.docx"]],
      ["transient", ["avbruten.pdf"]]
    ]);
    expect(problems.intentional.map((group) => group.category)).toEqual(["unsupported"]);
    expect(problems.fixable[0]?.files[1]?.item).toBe(b);
    expect(problems.causeCount).toBe(4);
  });

  it("leaves out files an older version listed as skipped because they were unchanged", () => {
    const a = item("a");
    const problems = buildSourceProblems(
      [a],
      {
        a: skipped([
          ["samma.docx", "unchanged"],
          ["scan.pdf", "no_text_layer"]
        ])
      },
      t
    );

    expect(problems.fixable.flatMap((group) => group.files.map((f) => f.file))).toEqual([
      "scan.pdf"
    ]);
    expect(problems.intentional).toEqual([]);
    expect(problems.causeCount).toBe(1);
  });

  it("counts a file set aside after failed attempts as a passing problem that is tried again", () => {
    const problems = buildSourceProblems(
      [item("a")],
      { a: skipped([["trasig.docx", "set_aside"]]) },
      t
    );
    expect(problems.fixable.map((group) => group.category)).toEqual(["transient"]);
    expect(problems.causeCount).toBe(1);
  });

  it("collects sign-in failures once and other failures per message", () => {
    const problems = buildSourceProblems(
      [
        item("a", {
          last_sync_status: "error",
          last_sync_error: CREDENTIALS,
          last_synced_at: "2026-10-01T10:00:00Z"
        }),
        item("b", {
          last_sync_status: "error",
          last_sync_error: CREDENTIALS,
          last_synced_at: "2026-10-03T10:00:00Z"
        }),
        item("c", { last_sync_status: "error", last_sync_error: " Graph timeout " }),
        item("d", { last_sync_status: "error", last_sync_error: "Graph timeout" }),
        item("e", { last_sync_status: "error", last_sync_error: "itemNotFound" })
      ],
      {},
      t
    );

    expect(problems.credentials?.items.map((i) => i.id)).toEqual(["a", "b"]);
    expect(problems.credentials?.lastSyncedAt).toBe("2026-10-03T10:00:00Z");
    expect(problems.failures.map((f) => [f.message, f.items.map((i) => i.id)])).toEqual([
      ["Graph timeout", ["c", "d"]],
      ["itemNotFound", ["e"]]
    ]);
    expect(problems.causeCount).toBe(3);
  });

  it("reports capped lists and lists that could not be loaded", () => {
    const failed = item("b");
    const problems = buildSourceProblems(
      [item("a"), failed],
      {
        a: skipped([["x.png", "unsupported_type"]], {
          total: 40,
          truncated: true,
          synced_at: "2026-10-14T03:00:00Z"
        }),
        b: null
      },
      t
    );

    expect(problems.notListed).toBe(39);
    expect(problems.skippedAsOf).toBe("2026-10-14T03:00:00Z");
    expect(problems.unavailable).toEqual([failed]);
    expect(problems.causeCount).toBe(0);
  });
});
