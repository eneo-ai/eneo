"use client";

import { Wrench } from "lucide-react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { useSpace } from "@/features/spaces/use-space";
import { ServiceActions } from "./actions";
import type { ServiceSparse } from "./services";

/** Grid tile for a service; clicking it opens the playground. */
export function ServiceTile({ service }: { service: ServiceSparse }) {
  const { routeId } = useSpace();

  return (
    <Card className="group hover:border-primary/40 relative gap-0 p-4 transition-colors">
      <Link
        href={`/spaces/${routeId}/services/${service.id}?tab=playground`}
        className="flex flex-col items-center gap-3 pt-2 pb-1 text-center after:absolute after:inset-0"
        aria-label={service.name}
      >
        <span className="bg-muted text-muted-foreground flex size-16 items-center justify-center rounded-xl">
          <Wrench className="size-7" />
        </span>
        <span className="line-clamp-2 text-sm font-medium">{service.name}</span>
      </Link>
      <div className="absolute top-2 right-2 z-10 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
        <ServiceActions service={service} />
      </div>
    </Card>
  );
}
