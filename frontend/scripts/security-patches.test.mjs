import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

// Exercise the patched copy reached through the actual dependency chain.
const docs = createRequire(
  new URL("../apps/docs-site/package.json", import.meta.url),
);
const nextra = createRequire(docs.resolve("nextra"));
const glob = createRequire(nextra.resolve("fast-glob"));
const match = createRequire(glob.resolve("micromatch"));
const braces = match("braces");

function nestedAst() {
  let ast = { type: "text", value: "a" };
  for (let depth = 0; depth < 101; depth++)
    ast = { type: "brace", nodes: [ast] };
  return { type: "root", nodes: [ast] };
}

test("ordinary build glob patterns still compile and expand", () => {
  assert.deepEqual(braces.expand("src/{a,b}.{ts,tsx}"), [
    "src/a.ts",
    "src/a.tsx",
    "src/b.ts",
    "src/b.tsx",
  ]);
  assert.deepEqual(braces("a/{b,c}/d"), ["a/(b|c)/d"]);
  assert.deepEqual(braces.expand("foo/({a,b})"), ["foo/(a)", "foo/(b)"]);
  assert.equal(
    braces.stringify(braces.parse("{a,{b,{c}}"), { escapeInvalid: true }),
    "{a,{b,{c}}",
  );
});

test("CVE-2026-93687: all string entry points reject excessive nesting before recursion", () => {
  for (const pattern of [
    "{".repeat(101) + "a,b" + "}".repeat(101),
    "(".repeat(101) + "a" + ")".repeat(101),
    "{(".repeat(51) + "a,b" + ")}".repeat(51),
  ]) {
    for (const operation of [
      braces,
      braces.parse,
      braces.compile,
      braces.expand,
    ]) {
      assert.throws(() => operation(pattern), /exceeds max depth/);
    }
  }
  assert.throws(
    () => braces.parse("{{a,b},c}", { maxDepth: 1.5 }),
    /exceeds max depth/,
  );
  assert.throws(
    () =>
      braces.parse("{".repeat(101) + "a" + "}".repeat(101), {
        maxDepth: Infinity,
      }),
    /exceeds max depth/,
  );
});

test("prebuilt ASTs cannot bypass the depth guard", () => {
  for (const operation of [braces.compile, braces.expand, braces.stringify]) {
    assert.throws(() => operation(nestedAst()), /exceeds max depth/);
  }
});

test("cyclic parent references fail instead of hanging", () => {
  const ast = { type: "paren", nodes: [{ type: "text", value: "a" }] };
  ast.parent = ast;
  assert.throws(
    () =>
      vm.runInNewContext(
        "braces.expand(ast)",
        { braces, ast },
        { timeout: 250 },
      ),
    /parent chain contains a cycle/,
  );
});
