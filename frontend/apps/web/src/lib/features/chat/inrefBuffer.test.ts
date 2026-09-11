import { describe, expect, it } from "vitest";
import { splitPendingInref } from "./inrefBuffer";

const A = '<inref id="aaaaaaaa"/>';
const B = '<inref id="bbbbbbbb"/>';

describe("splitPendingInref", () => {
  it("releases text without a possible tag", () => {
    expect(splitPendingInref("plain text")).toEqual(["plain text", ""]);
    expect(splitPendingInref("1 < 2 and 3 > 2")).toEqual(["1 < 2 and 3 > 2", ""]);
  });

  it("withholds an unfinished tag, however short", () => {
    expect(splitPendingInref("Se <")).toEqual(["Se ", "<"]);
    expect(splitPendingInref("Se <inr")).toEqual(["Se ", "<inr"]);
    expect(splitPendingInref('Se <inref id="aaaa')).toEqual(["Se ", '<inref id="aaaa']);
  });

  it("releases a complete tag", () => {
    expect(splitPendingInref(`Se ${A} mer`)).toEqual([`Se ${A} mer`, ""]);
    expect(splitPendingInref('<inref id="x"></inref>')).toEqual(['<inref id="x"></inref>', ""]);
  });

  it("releases earlier complete citations but not a trailing unfinished one", () => {
    expect(splitPendingInref(`${A} mer <inref id="bbbb`)).toEqual([`${A} mer `, '<inref id="bbbb']);
    expect(splitPendingInref(`a < b ${A}<`)).toEqual([`a < b ${A}`, "<"]);
  });

  it("never shows a partial tag, whichever way the stream is split", () => {
    const answer = `Se ${A} och ${B} för mer.`;
    for (let cut = 1; cut < answer.length; cut++) {
      for (let cut2 = cut + 1; cut2 <= answer.length; cut2++) {
        const chunks = [answer.slice(0, cut), answer.slice(cut, cut2), answer.slice(cut2)];
        let pending = "";
        let shown = "";
        for (const chunk of chunks) {
          const [ready, rest] = splitPendingInref(pending + chunk);
          pending = rest;
          shown += ready;
          // Every prefix shown so far must not end inside a citation tag.
          expect(shown, `after chunks ${JSON.stringify(chunks)}`).not.toMatch(/<inref[^>]*$/);
          expect(shown).not.toMatch(/<(i(n(r(e)?)?)?)?$/);
        }
        expect(shown + pending).toBe(answer);
      }
    }
  });
});
