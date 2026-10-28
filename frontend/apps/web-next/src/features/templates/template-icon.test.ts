import { expect, it } from "vitest";
import { templateIconName } from "./template-icon";

it("finds a stored icon name however it is written, and nothing for an unknown one", () => {
  expect(templateIconName("message-square")).toBe("message-square");
  expect(templateIconName("MessageSquare")).toBe("message-square");
  // The Svelte picker stored `ArrowDown01` as `arrow-down01` (lucide-react's
  // `arrow-down-0-1`, or its alias `arrow-down-01`).
  expect(templateIconName("arrow-down01")).toMatch(/^arrow-down-0-?1$/);
  // Lucide's alias for a renamed icon.
  expect(templateIconName("home")).toBe("home");
  expect(templateIconName("no-such-icon")).toBeNull();
  expect(templateIconName(null)).toBeNull();
  expect(templateIconName("")).toBeNull();
});
