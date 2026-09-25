"use client";

import { useTranslations } from "next-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { ResourceCard } from "@/components/composites/resource-tile";
import { useSpace } from "@/features/spaces/use-space";
import { ServiceActions } from "./actions";
import type { ServiceSparse } from "./services";

const OUTPUT_FORMAT_KEYS = {
  json: "space_service_output_json",
  list: "space_service_output_list",
  boolean: "space_service_output_boolean"
} as const;

/** Card for a service; the card opens its playground. */
export function ServiceTile({ service }: { service: ServiceSparse }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const format = service.output_format ? OUTPUT_FORMAT_KEYS[service.output_format] : null;

  return (
    <ResourceCard
      href={`/spaces/${routeId}/services/${service.id}?tab=playground`}
      name={service.name}
      tile={<EntityAvatar name={service.name} id={service.id} size="lg" className="size-9" />}
      meta={format ? [t(format)] : undefined}
      actions={<ServiceActions service={service} />}
    />
  );
}
