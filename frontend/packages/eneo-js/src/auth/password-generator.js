/**
 * @typedef {{
 *   minLength: number,
 *   maxBytes: number | null,
 *   requiresUppercase: boolean,
 *   requiresLowercase: boolean,
 *   requiresNumber: boolean,
 *   requiresSymbol: boolean
 * }} LocalPasswordPolicy
 *
 * The backend's local password policy (GET /api/v1/users/password-policy/,
 * owned by eneo/users/password.py) as both apps normalize it. The minimum
 * counts characters, the maximum UTF-8 bytes, and the classes are ASCII.
 */

/**
 * Generated passwords are at least this long; a policy may ask for more. At 65
 * possible characters each, that is about 120 bits of entropy.
 */
export const GENERATED_PASSWORD_LENGTH = 20;

/**
 * ASCII only, so a password's UTF-8 byte count is its length. Characters that
 * are misread when a password is handed over (0/O/o, 1/l/I) are left out, as
 * are quotes, backslash and space.
 */
export const PASSWORD_CHARACTER_CLASSES = Object.freeze({
  uppercase: "ABCDEFGHJKLMNPQRSTUVWXYZ",
  lowercase: "abcdefghijkmnpqrstuvwxyz",
  number: "23456789",
  symbol: "!#%+-=?@_"
});

const ALPHABET = Object.values(PASSWORD_CHARACTER_CLASSES).join("");

/**
 * A random password that meets `policy`: as long as its minimum asks, but never
 * shorter than GENERATED_PASSWORD_LENGTH unless its byte limit forces it, with a
 * character of every class it requires. Draws from the platform's
 * cryptographic random source.
 *
 * @param {LocalPasswordPolicy} policy
 * @returns {string}
 * @throws {RangeError} when no password can meet the policy
 */
export function generatePassword(policy) {
  /** @type {string[]} */
  const requiredClasses = [];
  if (policy.requiresUppercase) requiredClasses.push(PASSWORD_CHARACTER_CLASSES.uppercase);
  if (policy.requiresLowercase) requiredClasses.push(PASSWORD_CHARACTER_CLASSES.lowercase);
  if (policy.requiresNumber) requiredClasses.push(PASSWORD_CHARACTER_CLASSES.number);
  if (policy.requiresSymbol) requiredClasses.push(PASSWORD_CHARACTER_CLASSES.symbol);

  const length = Math.min(
    Math.max(policy.minLength, GENERATED_PASSWORD_LENGTH),
    policy.maxBytes ?? Number.POSITIVE_INFINITY
  );
  if (length < policy.minLength || length < requiredClasses.length) {
    throw new RangeError(
      "No password can meet this policy: its byte limit leaves no room for its minimum length or required characters."
    );
  }

  const characters = requiredClasses.map(pick);
  while (characters.length < length) characters.push(pick(ALPHABET));
  // Fisher–Yates, so the required characters do not always lead.
  for (let i = characters.length - 1; i > 0; i--) {
    const j = randomIndex(i + 1);
    [characters[i], characters[j]] = [characters[j], characters[i]];
  }
  return characters.join("");
}

/** @param {string} characters */
function pick(characters) {
  return characters[randomIndex(characters.length)];
}

/**
 * A uniform integer below `bound`. Values past the last whole multiple of
 * `bound` are drawn again, since keeping them would favour small results.
 *
 * @param {number} bound
 */
function randomIndex(bound) {
  const limit = 2 ** 32 - (2 ** 32 % bound);
  const value = new Uint32Array(1);
  do {
    globalThis.crypto.getRandomValues(value);
  } while (value[0] >= limit);
  return value[0] % bound;
}
