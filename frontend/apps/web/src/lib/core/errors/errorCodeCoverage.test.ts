import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import en from "../../../../messages/en.json";
import sv from "../../../../messages/sv.json";

/**
 * A backend reason code with no localized message silently falls back to the
 * backend's English string. That is a documented fallback, not a crash, so
 * nothing used to notice when a new code shipped without Swedish copy.
 *
 * `ErrorCodes` is enumerated from the generated SDK types, which the schema
 * drift job already holds equal to the backend enum, so this test fails the
 * moment a new code arrives without a decision about its copy.
 */
const SCHEMA_PATH = fileURLToPath(
  new URL("../../../../../../packages/eneo-js/src/types/schema.d.ts", import.meta.url)
);

/**
 * Codes deliberately left on the backend's English message. Each entry needs a
 * reason; this list should shrink, never grow. A code belongs here only when a
 * localized message would be wrong or useless, not merely unwritten.
 */
const UNLOCALIZED_BY_DESIGN = new Map<number, string>([
  // Generic HTTP shapes. The backend message is the specific one; a localized
  // "not found" or "bad request" would replace detail with a platitude.
  [9000, "NOT_FOUND — callers render their own not-found state"],
  [9007, "BAD_REQUEST — the backend message carries the actual reason"],
  [9012, "VALIDATION_ERROR — field-level detail lives in the response"],
  [9013, "PYDANTIC_PARSE_ERROR — developer-facing, never shown as-is"],

  // Infrastructure and operator conditions. These reach logs and admins, not
  // end users in a normal session.
  [9003, "QUERY_ERROR — internal persistence failure"],
  [9016, "CHUNK_EMBEDDING_MISMATCH — internal ingestion invariant"],
  [9022, "IAM_EXCEPTION — operator-facing identity provider failure"],
  [9023, "INTERNAL_HTTP_ERROR — upstream transport failure"],
  [9018, "PROVISIONING_NOT_ENABLED — deployment configuration"],
  [9040, "SYSTEM_USER_PROTECTED — operator-facing guard"],

  // Account lifecycle, surfaced only in admin flows that show the raw message.
  [9004, "UNIQUE_USER_ERROR — admin user administration"],
  [9006, "USER_NOT_CREATED — admin user administration"],
  [9009, "UNIQUE_ERROR — generic uniqueness, message names the field"],

  // Owned by areas outside the Skills tranche. Localizing them is real work
  // with real product decisions, tracked separately rather than guessed at.
  [9014, "FILE_NOT_SUPPORTED — files"],
  [9015, "FILE_TOO_LARGE — files, message carries the limit"],
  [9027, "FILE_EXTRACTION_ERROR — files"],
  [9028, "FILE_ENCRYPTED — files"],
  [9029, "FILE_CORRUPT — files"],
  [9030, "FILE_FORMAT_UNSUPPORTED — files"],
  [9044, "FILE_IN_USE — files"],
  [9045, "FILE_ORIGINAL_NOT_FOUND — files"],
  [9046, "DEPLOYMENT_POLICY_CONFLICT — object content deployment"],
  [9047, "OBJECT_STORE_NOT_SELECTABLE — object content deployment"],
  [9021, "CRAWL_ALREADY_RUNNING — crawler"],
  [9032, "PROVIDER_NOT_FOUND — model providers"],
  [9041, "PROVIDER_REJECTED_REQUEST — message quotes the provider"]
]);

function backendErrorCodes(): number[] {
  const schema = readFileSync(SCHEMA_PATH, "utf8");
  const union = /ErrorCodes:\s*((?:\s*\|\s*\d+)+)/.exec(schema);
  if (!union) throw new Error("ErrorCodes union not found in generated schema.d.ts");
  return [...union[1].matchAll(/\d+/g)].map((match) => Number(match[0]));
}

function localizedCodes(): Set<number> {
  const source = readFileSync(
    fileURLToPath(new URL("./getErrorMessage.ts", import.meta.url)),
    "utf8"
  );
  return new Set([...source.matchAll(/^ {2}(\d{4}):/gm)].map((match) => Number(match[1])));
}

describe("error code localization coverage", () => {
  it("localizes every backend reason code that is not explicitly exempt", () => {
    const missing = backendErrorCodes().filter(
      (code) => !localizedCodes().has(code) && !UNLOCALIZED_BY_DESIGN.has(code)
    );

    expect(
      missing,
      `Add "eneo_error_<code>" to messages/en.json and messages/sv.json and map it in ` +
        `getErrorMessage.ts, or record why the backend message is better in ` +
        `UNLOCALIZED_BY_DESIGN.`
    ).toEqual([]);
  });

  it("keeps every mapped code backed by both catalogues", () => {
    const catalogues = { en, sv } as Record<string, Record<string, string>>;

    for (const code of localizedCodes()) {
      for (const [language, catalogue] of Object.entries(catalogues)) {
        const message = catalogue[`eneo_error_${code}`];
        expect(message, `eneo_error_${code} in ${language}.json`).toBeTruthy();
        expect(message?.trim(), `eneo_error_${code} in ${language}.json`).not.toBe("");
      }
    }
  });

  /**
   * `SkillSlugConflictError` is raised once, in the repository
   * (`skill_repo_impl.py:308`), for both the Space catalogue and the
   * organisation catalogue. One code therefore serves both scopes, and its
   * message cannot name the one it thinks it is in — an organisation
   * collision described as a Space collision sends the administrator to look
   * in the wrong catalogue.
   */
  it("keeps the identifier conflict message free of a scope it cannot know", () => {
    const SCOPE_WORDS = [/\bspace\b/i, /\borganisation\b/i, /\borganization\b/i, /\bkatalog/i];

    for (const catalogue of [en, sv] as Record<string, string>[]) {
      const message = catalogue.eneo_error_9048;
      expect(message).toBeTruthy();
      for (const word of SCOPE_WORDS) {
        expect(message, `eneo_error_9048 names a scope: ${word}`).not.toMatch(word);
      }
    }
  });

  it("does not exempt a code that is already localized", () => {
    const contradictory = [...UNLOCALIZED_BY_DESIGN.keys()].filter((code) =>
      localizedCodes().has(code)
    );

    expect(contradictory, "remove these from UNLOCALIZED_BY_DESIGN").toEqual([]);
  });

  it("does not exempt a code the backend no longer defines", () => {
    const backend = new Set(backendErrorCodes());
    const stale = [...UNLOCALIZED_BY_DESIGN.keys()].filter((code) => !backend.has(code));

    expect(stale, "remove these from UNLOCALIZED_BY_DESIGN").toEqual([]);
  });
});
