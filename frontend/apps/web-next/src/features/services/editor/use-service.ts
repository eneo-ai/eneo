import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { serviceQueryOptions, type Service, type ServiceUpdate } from "../services";

export { serviceQueryOptions };

/**
 * Service update via POST /api/v1/services/{id}/ (POST-as-update is RB-5(b)).
 * Refreshes both the service and the space list.
 */
export function useUpdateService(serviceId: string, onSuccess?: (service: Service) => void) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: ServiceUpdate) =>
      unwrap(
        browserApi.POST("/api/v1/services/{id}/", { params: { path: { id: serviceId } }, body })
      ),
    onSuccess: (service) => {
      queryClient.setQueryData(serviceQueryOptions(browserApi, serviceId).queryKey, service);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      onSuccess?.(service);
    },
    onError: (error) => toastApiError(error, t)
  });
}
