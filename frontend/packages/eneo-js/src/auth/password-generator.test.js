import assert from "node:assert/strict";
import test from "node:test";
import {
  GENERATED_PASSWORD_LENGTH,
  PASSWORD_CHARACTER_CLASSES,
  generatePassword
} from "./password-generator.js";

const backendPolicy = {
  minLength: 12,
  maxBytes: 72,
  requiresUppercase: false,
  requiresLowercase: false,
  requiresNumber: false,
  requiresSymbol: false
};

// The backend's checks (eneo/users/password.py), not the generator's classes.
const classChecks = {
  requiresUppercase: /[A-Z]/,
  requiresLowercase: /[a-z]/,
  requiresNumber: /[0-9]/,
  requiresSymbol: /[^A-Za-z0-9]/
};

/** Every combination of required classes. */
function classCombinations() {
  const flags = Object.keys(classChecks);
  return Array.from({ length: 2 ** flags.length }, (_, mask) =>
    Object.fromEntries(flags.map((flag, bit) => [flag, (mask & (1 << bit)) !== 0]))
  );
}

test("passwords meet every combination of the policy's rules", () => {
  for (const classes of classCombinations()) {
    for (const [minLength, maxBytes] of [
      [1, 72],
      [12, 72],
      [12, null],
      [32, 72],
      [72, 72],
      [12, 16]
    ]) {
      const policy = { ...backendPolicy, ...classes, minLength, maxBytes };
      for (let i = 0; i < 50; i++) {
        const password = generatePassword(policy);
        const bytes = new TextEncoder().encode(password).byteLength;
        assert.ok([...password].length >= minLength, `${password} is shorter than ${minLength}`);
        if (maxBytes !== null)
          assert.ok(bytes <= maxBytes, `${password} exceeds ${maxBytes} bytes`);
        for (const [flag, pattern] of Object.entries(classChecks)) {
          if (policy[flag]) assert.match(password, pattern, `${flag} missing from ${password}`);
        }
      }
    }
  }
});

test("a required class is guaranteed, not left to chance", () => {
  const everyClass = {
    minLength: 4,
    maxBytes: 4,
    requiresUppercase: true,
    requiresLowercase: true,
    requiresNumber: true,
    requiresSymbol: true
  };
  for (let i = 0; i < 500; i++) {
    const password = generatePassword(everyClass);
    assert.equal(password.length, 4);
    for (const pattern of Object.values(classChecks)) assert.match(password, pattern);
  }
});

test("the length follows the policy's minimum and byte limit", () => {
  assert.equal(generatePassword(backendPolicy).length, GENERATED_PASSWORD_LENGTH);
  assert.equal(generatePassword({ ...backendPolicy, minLength: 40 }).length, 40);
  assert.equal(generatePassword({ ...backendPolicy, maxBytes: 16 }).length, 16);
  assert.equal(
    generatePassword({ ...backendPolicy, maxBytes: null }).length,
    GENERATED_PASSWORD_LENGTH
  );
});

test("a policy no password can meet is refused", () => {
  assert.throws(() => generatePassword({ ...backendPolicy, minLength: 80 }), RangeError);
  assert.throws(
    () =>
      generatePassword({
        ...backendPolicy,
        minLength: 1,
        maxBytes: 3,
        requiresUppercase: true,
        requiresLowercase: true,
        requiresNumber: true,
        requiresSymbol: true
      }),
    RangeError
  );
});

test("every character of the alphabet is drawn, and nothing else", () => {
  const alphabet = new Set(Object.values(PASSWORD_CHARACTER_CLASSES).join(""));
  const seen = new Set();
  for (let i = 0; i < 2_000; i++) {
    for (const character of generatePassword(backendPolicy)) seen.add(character);
  }
  assert.deepEqual([...seen].sort(), [...alphabet].sort());
  for (const lookalike of "0Oo1lI\"'` \\") assert.ok(!alphabet.has(lookalike), lookalike);
});

/** Counts calls to a method; node:test's `mock` is missing under bun test. */
function countCalls(object, name) {
  const own = Object.getOwnPropertyDescriptor(object, name);
  const original = object[name];
  const spy = {
    count: 0,
    restore: () => (own ? Object.defineProperty(object, name, own) : delete object[name])
  };
  object[name] = function (...args) {
    spy.count += 1;
    return original.apply(this, args);
  };
  return spy;
}

test("randomness comes from the platform's cryptographic source only", () => {
  const getRandomValues = countCalls(globalThis.crypto, "getRandomValues");
  const random = countCalls(Math, "random");
  try {
    generatePassword(backendPolicy);
    assert.ok(getRandomValues.count >= GENERATED_PASSWORD_LENGTH);
    assert.equal(random.count, 0);
  } finally {
    getRandomValues.restore();
    random.restore();
  }
});

test("passwords do not repeat", () => {
  const passwords = new Set(Array.from({ length: 1_000 }, () => generatePassword(backendPolicy)));
  assert.equal(passwords.size, 1_000);
});
