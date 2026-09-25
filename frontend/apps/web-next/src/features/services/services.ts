import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { Space } from "@/features/spaces/space";

export type Service = Schema<"ServicePublicWithUser">;
export type ServiceSparse = Schema<"ServiceSparse">;
export type ServiceUpdate = Schema<"PartialServiceUpdatePublic">;
export type ServiceOutputFormat = "json" | "list" | "boolean";

/** Services configured in a space, name-sorted with the locale's collator (Astryx `useCollator().compare`). */
export function spaceServices(space: Space, compare: Intl.Collator["compare"]): ServiceSparse[] {
  return [...(space.applications?.services.items ?? [])].sort((a, b) => compare(a.name, b.name));
}

export function serviceQueryOptions(api: EneoClient, serviceId: string) {
  return queryOptions({
    queryKey: ["services", serviceId],
    queryFn: (): Promise<Service> =>
      unwrap(api.GET("/api/v1/services/{id}/", { params: { path: { id: serviceId } } }))
  });
}
