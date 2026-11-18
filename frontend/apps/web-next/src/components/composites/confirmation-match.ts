/**
 * Whether what was typed to confirm an action is the name shown for it. The
 * comparison is exact except for what a phone keyboard adds without being
 * asked: a space after a tapped suggestion, and a decomposed å, ä or ö.
 * (Fields that confirm by typing set KEYBOARD.identifier, so the first letter
 * is not capitalised and nothing is auto-corrected.)
 */
export function confirmationMatches(typed: string, expected: string): boolean {
  return typed.trim().normalize("NFC") === expected.trim().normalize("NFC");
}
