import { describe, expect, it } from "vitest";
import { TEMPLATE_ICON_NAMES, storedTemplateIconName, templateIconName } from "./template-icon";

/** Lucide's export name for an icon name (its own toPascalCase). */
const lucidePascal = (name: string) =>
  name.replace(/(^|-)(\w)/g, (_match, _dash, letter: string) => letter.toUpperCase());
/** How the Svelte reader (apps/web lucideIcons.ts toPascalCase) turns a stored name back. */
const sveltePascal = (name: string) =>
  name.charAt(0).toUpperCase() + name.slice(1).replace(/-([a-z])/g, (g) => g[1]!.toUpperCase());

describe("template icon names", () => {
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

  // The Svelte reader's rule, not its registry: web-next cannot depend on the
  // Svelte app, whose older Lucide lacks the newest icons.
  it("stores a picked icon in a form both readers turn back into its Lucide name", () => {
    expect(storedTemplateIconName("building-2")).toBe("building2");
    expect(storedTemplateIconName("arrow-down-0-1")).toBe("arrow-down01");
    expect(storedTemplateIconName("a-arrow-down")).toBe("a-arrow-down");
    for (const name of TEMPLATE_ICON_NAMES) {
      const stored = storedTemplateIconName(name);
      expect(sveltePascal(stored), name).toBe(lucidePascal(name));
      expect(templateIconName(stored), name).not.toBeNull();
    }
  });
});
