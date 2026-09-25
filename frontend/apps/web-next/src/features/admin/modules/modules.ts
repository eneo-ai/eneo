import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ModuleInstallation = Schema<"ModuleInstallation">;
export type ServiceKey = Schema<"ApiKeyV2">;

/** Keep the backend as the authority for binding eligibility, across every page. */
export async function listCompatibleServiceKeys(): Promise<ServiceKey[]> {
  const keys: ServiceKey[] = [];
  const visited = new Set<string>();
  let cursor: string | null = null;

  do {
    const page: Schema<"CursorPaginatedResponse_ApiKeyV2_"> = await unwrap(
      browserApi.GET("/api/v1/admin/api-keys", {
        params: {
          query: { limit: 200, eligible_for_module_binding: true, ...(cursor && { cursor }) }
        }
      })
    );
    for (const key of page.items) {
      if (!keys.some((existing) => existing.id === key.id)) keys.push(key);
    }
    const next: string | null = page.next_cursor ?? null;
    if (next && visited.has(next))
      throw new Error("API key pagination returned a repeated cursor.");
    if (next) visited.add(next);
    cursor = next;
  } while (cursor);

  return keys;
}

export function parseRedirectUris(input: string): string[] {
  return [
    ...new Set(
      input
        .split(/\r?\n/)
        .map((uri) => uri.trim())
        .filter(Boolean)
    )
  ];
}

export function serviceKeyLabel(key: ServiceKey): string {
  return `${key.name} · ${key.key_prefix}••••${key.key_suffix}`;
}

/** Missing former bindings require an explicit new selection before saving. */
export function initialServiceKeySelection(
  installation: ModuleInstallation,
  compatibleKeys: ServiceKey[]
): { selection: string; missing: boolean } {
  const bound = installation.service_key_id;
  if (!bound) return { selection: "__unbound__", missing: false };
  if (compatibleKeys.some((key) => key.id === bound)) return { selection: bound, missing: false };
  return { selection: "", missing: true };
}
