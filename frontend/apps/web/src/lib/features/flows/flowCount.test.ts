import { describe, expect, it } from "vitest";
import { getLocale, setLocale } from "$lib/paraglide/runtime";
import { countMessage, formatCount } from "./flowCount";

const one = () => "one file";
const many = ({ count }: { count: string }) => `${count} files`;

describe("countMessage", () => {
  it("uses the singular sentence for exactly one", () => {
    expect(countMessage(1, one, many)).toBe("one file");
  });

  it("uses the plural sentence for zero and for several", () => {
    expect(countMessage(0, one, many)).toBe("0 files");
    expect(countMessage(3, one, many)).toBe("3 files");
  });

  it("writes large numbers the way the active language does", () => {
    const previous = getLocale();
    try {
      setLocale("en", { reload: false });
      expect(countMessage(1200, one, many)).toBe("1,200 files");
      expect(formatCount(1200)).toBe("1,200");
      setLocale("sv", { reload: false });
      expect(formatCount(1200).replace(/\s/g, " ")).toBe("1 200");
    } finally {
      setLocale(previous, { reload: false });
    }
  });
});
