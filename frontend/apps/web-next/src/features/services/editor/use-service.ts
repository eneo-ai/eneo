import { useMutation, useQueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useSpace } from "@/features/spaces/use-space";
import { serviceQueryOptions, type Service, type ServiceUpdate } from "../services";

export { serviceQueryOptions };

/**
 * Service update via POST /api/v1/services/{id}/ (POST-as-update is RB-5(b)).
 * Refreshes both the service and the space list.
 */
export function useUpdateService(serviceId: string, onSuccess?: (service: Service) => void) {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();

  return useMutation({
    scope: { id: `service:${serviceId}` },
    mutationFn: (body: ServiceUpdate) =>
      unwrap(
        browserApi.POST("/api/v1/services/{id}/", { params: { path: { id: serviceId } }, body })
      ),
    onSuccess: (service) => {
      queryClient.setQueryData(serviceQueryOptions(browserApi, serviceId).queryKey, service);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      onSuccess?.(service);
    }
  });
}
