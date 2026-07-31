import { describe, expect, it } from "vitest";
import {
  getTemplateIconComponent,
  isTemplateIconName,
  normalizeTemplateIconName,
  templateIconOptions
} from "./templateIconRegistry";

describe("templateIconRegistry", () => {
  it("normalizes stored and UI icon names to one value shape", () => {
    expect(normalizeTemplateIconName("MessageSquare")).toBe("message-square");
    expect(normalizeTemplateIconName("message_square")).toBe("message-square");
    expect(normalizeTemplateIconName(" message square ")).toBe("message-square");
    expect(normalizeTemplateIconName("message-square")).toBe("message-square");
  });

  it("resolves supported icons and safely ignores unsupported persisted values", () => {
    expect(getTemplateIconComponent("message-square")).toBe(
      getTemplateIconComponent("MessageSquare")
    );
    expect(getTemplateIconComponent("does-not-exist")).toBeNull();
    expect(getTemplateIconComponent(null)).toBeNull();
    expect(getTemplateIconComponent(undefined)).toBeNull();
  });

  it("exposes a type guard for canonical persisted icon names", () => {
    expect(isTemplateIconName("message-square")).toBe(true);
    expect(isTemplateIconName("MessageSquare")).toBe(false);
    expect(isTemplateIconName("does-not-exist")).toBe(false);
  });

  it("keeps the curated registry unique and bounded", () => {
    const values = templateIconOptions.map((option) => option.value);
    const uniqueValues = new Set(values);

    expect(uniqueValues.size).toBe(values.length);
    expect(values.every((value) => /^[a-z][a-z0-9-]*$/.test(value))).toBe(true);
    expect(values.length).toBeGreaterThanOrEqual(40);
    expect(values.length).toBeLessThanOrEqual(80);
  });
});
