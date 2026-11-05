/** The whitespace collapse the API applies to names and visitor-facing texts. */
export function collapseWhitespace(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}
