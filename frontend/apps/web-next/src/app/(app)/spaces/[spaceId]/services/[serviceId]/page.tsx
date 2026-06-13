import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { serviceQueryOptions } from "@/features/services/services";
import { ServiceDetail } from "@/features/services/service-detail";

export default async function ServiceDetailPage({
  params
}: {
  params: Promise<{ spaceId: string; serviceId: string }>;
}) {
  const { serviceId } = await params;
  const queryClient = getQueryClient();

  try {
    await queryClient.fetchQuery(serviceQueryOptions(eneoApi(), serviceId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ServiceDetail serviceId={serviceId} />
    </HydrationBoundary>
  );
}
