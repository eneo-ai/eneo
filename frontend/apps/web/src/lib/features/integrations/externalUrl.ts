/**
 * An integration's link to the item in its source system, when it is safe to
 * render: only absolute https URLs. Anything else (another scheme such as
 * javascript:, a relative path, a malformed value) gives null, so no link is shown.
 */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}
