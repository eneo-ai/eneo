import { API_BASE } from "@/lib/api/base";

/**
 * Icon uploads are served under the API base, which authenticates the request.
 * Its own module: the shell's sidebar shows icons without the upload field.
 */
export function iconUrl(iconId: string | null | undefined): string | null {
  return iconId ? `${API_BASE}/api/v1/icons/${encodeURIComponent(iconId)}/` : null;
}
