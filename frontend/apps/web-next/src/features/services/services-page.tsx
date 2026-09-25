"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { SearchX, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { RESOURCE_GRID_CLASS } from "@/components/composites/resource-tile";
import { SpaceSectionHeader } from "@/features/spaces/frame/space-section-header";
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
  const collator = useCollator();
  const [filter, setFilter] = useState("");
  const services = spaceServices(space, collator.compare);
  const filteredServices = filterSpaceResources(services, filter);
  const canCreate = can("create", "service");

  return (
    <div className="flex w-full flex-col gap-6">
      <SpaceSectionHeader
        title={t("services")}
        actions={canCreate && services.length > 0 ? <CreateServiceButton /> : undefined}
      />
      {services.length === 0 ? (
        <EmptyState
          icon={<Wrench />}
          title={t("space_services_empty_title")}
          description={t("space_services_empty_description")}
          actions={canCreate ? <CreateServiceButton /> : undefined}
        />
      ) : (
        <>
          <ResourceFilterInput
            value={filter}
            onChange={setFilter}
            placeholder={t("ui_filter_items", { resourceName: t("resource_services") })}
          />
          {filteredServices.length === 0 ? (
            <EmptyState icon={<SearchX />} title={t("no_results_found")} isCompact />
          ) : (
            <ul className={RESOURCE_GRID_CLASS}>
              {filteredServices.map((service) => (
                <li key={service.id} className="min-w-0">
                  <ServiceTile service={service} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
