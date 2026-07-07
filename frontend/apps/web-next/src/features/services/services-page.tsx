"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { CreateServiceButton } from "./create-service";
import { spaceServices } from "./services";
import { ServiceTile } from "./tile";

/** Services grid for a space. */
export function ServicesPage() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const [filter, setFilter] = useState("");
  const services = spaceServices(space);
  const filteredServices = filterSpaceResources(services, filter);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("services")}>
        {can("create", "service") && <CreateServiceButton />}
      </PageHeader>
      {services.length === 0 ? (
        <EmptyState title={t("there_are_currently_no_services_configured")}>
          {can("create", "service") && <CreateServiceButton />}
        </EmptyState>
      ) : (
        <>
          <ResourceFilterInput
            value={filter}
            onChange={setFilter}
            placeholder={t("ui_filter_items", { resourceName: t("resource_services") })}
          />
          {filteredServices.length === 0 ? (
            <EmptyState title={t("no_results_found")} />
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
              {filteredServices.map((service) => (
                <ServiceTile key={service.id} service={service} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
