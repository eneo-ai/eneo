import { describe, expect, it } from "vitest";
import { minifyCss } from "../scripts/minify-css.mjs";
import { styles } from "./styles";

// Browsers keep the author's spacing inside var() fallbacks and @supports
// conditions; only there is a difference in whitespace not a difference.
const tokens = (value: string) => value.replace(/\s*([,:()])\s*/g, "$1").trim();

/** Selectors exactly, declarations and conditions token by token. */
function describeRules(rules: CSSRuleList): unknown[] {
  return Array.from(rules, (rule) => {
    if (rule instanceof CSSStyleRule) {
      const declarations = Array.from(rule.style, (name) => [
        name,
        tokens(rule.style.getPropertyValue(name))
      ]);
      return { selector: rule.selectorText, declarations };
    }
    if (rule instanceof CSSConditionRule) {
      return { condition: tokens(rule.conditionText), rules: describeRules(rule.cssRules) };
    }
    return rule.cssText;
  });
}

function parsed(css: string): unknown[] {
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(css);
  return describeRules(sheet.cssRules);
}

describe("the shipped stylesheet", () => {
  it("means exactly what the readable source says", () => {
    const shipped = minifyCss(styles);
    expect(shipped.length).toBeLessThan(styles.length);
    expect(parsed(shipped)).toEqual(parsed(styles));
  });

  it("would notice a lost combinator", () => {
    expect(parsed(":host([open]).launcher{display:none}")).not.toEqual(
      parsed(":host([open]) .launcher { display: none; }")
    );
  });
});
