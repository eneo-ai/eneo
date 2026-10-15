// What a script finds installed besides the standard library: exact decimal arithmetic and
// Swedish formatting, neither of which QuickJS has (it implements ECMA-262 only, no Intl).
// Bundled by scripts/build-prelude.ts into one plain script that the engine evaluates in each
// fresh context before the script, as non-enumerable globals a script cannot replace or delete.
// Decimal itself stays as the library ships it: a script may call Decimal.set({ precision })
// for its own run, and the library writes `constructor` on each instance. Every call gets a
// fresh runtime, so nothing a script changes outlives it.
import Decimal from "decimal.js";
import * as fmt from "./fmt";

const install = (name: string, value: unknown) =>
  Object.defineProperty(globalThis, name, {
    value,
    writable: false,
    configurable: false,
    enumerable: false,
  });

install("Decimal", Decimal);
install("fmt", Object.freeze({ ...fmt }));
