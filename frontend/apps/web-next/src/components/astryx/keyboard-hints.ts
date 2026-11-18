/**
 * What a phone's on-screen keyboard does for a field, set on the `<input>`
 * (Astryx's TextInput, Typeahead and CommandPaletteInput pass unknown
 * attributes through; their types leave these out, so spread the preset):
 *
 * - `search`: a search key instead of a line break, no capital on the first
 *   letter, no auto-correction or red spell-check marks under what is filtered
 * - `email`: the keyboard with "@" and ".", otherwise as `identifier`
 * - `identifier`: user names, slugs, codes: typed as written
 *
 * Without them a filter field gets a return key and a capital first letter,
 * and an address field has no "@" until the user finds it on the symbol page.
 *
 * @example <TextInput label={t("email")} {...KEYBOARD.email} />
 */
export const KEYBOARD = {
  search: {
    enterKeyHint: "search",
    inputMode: "search",
    autoCapitalize: "none",
    autoCorrect: "off",
    spellCheck: false
  },
  email: {
    inputMode: "email",
    autoCapitalize: "none",
    autoCorrect: "off",
    spellCheck: false
  },
  identifier: {
    autoCapitalize: "none",
    autoCorrect: "off",
    spellCheck: false
  }
} as const;
