import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";
import { MAX_DAILY_TOKEN_BUDGET } from "./limits";

// The generated types carry no maximum, so nothing else keeps this copy equal
// to the API's; the backend has the mirror of this test.
const WIDGET_DOMAIN = fileURLToPath(
  new URL("../../../../../../../../backend/src/eneo/widgets/domain/widget.py", import.meta.url)
);

test("the budget ceiling the editors check is the API's", () => {
  const ceiling = /^MAX_DAILY_TOKEN_BUDGET = ([\d_]+)$/m.exec(readFileSync(WIDGET_DOMAIN, "utf8"));
  expect(ceiling).not.toBeNull();
  expect(Number(ceiling![1].replaceAll("_", ""))).toBe(MAX_DAILY_TOKEN_BUDGET);
});
