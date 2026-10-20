/** The key a new step gets from its name: a stable, template-safe identifier. */

const KEY_MAX_LENGTH = 64;

const TRANSLITERATIONS: Record<string, string> = {
  å: "a",
  ä: "a",
  ö: "o",
  æ: "ae",
  ø: "o",
  é: "e",
  è: "e",
  ü: "u"
};

/** "Sammanfatta beslut" → "sammanfatta_beslut": lower case, letters, digits and underscores, starting with a letter. */
export function slugifyKey(name: string): string {
  const slug = name
    .toLocaleLowerCase()
    .replace(/[åäöæøéèü]/g, (char) => TRANSLITERATIONS[char] ?? char)
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, KEY_MAX_LENGTH)
    .replace(/_+$/g, "");
  if (!slug) return "steg";
  return /^[a-z]/.test(slug) ? slug : `steg_${slug}`.slice(0, KEY_MAX_LENGTH);
}

/** A key no other step has: the slug, else the slug with a number. */
export function uniqueKey(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const base = slugifyKey(name);
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) {
    const suffix = `_${n}`;
    const candidate = `${base.slice(0, KEY_MAX_LENGTH - suffix.length)}${suffix}`;
    if (!used.has(candidate)) return candidate;
  }
}
