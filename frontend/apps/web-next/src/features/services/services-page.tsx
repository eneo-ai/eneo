"use client";

import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { useSpace } from "@/features/spaces/use-space";
import { CreateServiceButton } from "./create-service";
import { spaceServices } from "./services";
import { ServiceTile } from "./tile";

/** Services grid for a space. */
export function ServicesPage() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const services = spaceServices(space);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("services")}>
        {can("create", "service") && <CreateServiceButton />}
      </PageHeader>
      {services.length === 0 ? (
        <EmptyState title={t("there_are_currently_no_services_configured")} />
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {services.map((service) => (
            <ServiceTile key={service.id} service={service} />
          ))}
        </div>
      )}
    </div>
  );
}
