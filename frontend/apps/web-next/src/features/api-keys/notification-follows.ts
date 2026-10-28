import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { API_KEY_SUBSCRIPTIONS_KEY, invalidateExpiringApiKeys } from "./api-keys";

export type FollowTargetType = Schema<"ApiKeyNotificationTargetType">;
type Subscriptions = Schema<"ApiKeyNotificationSubscriptionListResponse">;

/** The keys, assistants, apps and spaces whose expiring keys the user is reminded of. */
export function apiKeyNotificationSubscriptionsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: API_KEY_SUBSCRIPTIONS_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/api-keys/notification-subscriptions")),
    staleTime: 60_000
  });
}

/**
 * The user's expiry reminders: which keys and scopes they follow, and the
 * toggle. A followed scope covers all its keys. A change refreshes the
 * shell's expiring-keys bell.
 */
export function useNotificationFollows({ enabled = true }: { enabled?: boolean } = {}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const subscriptions = useQuery({
    ...apiKeyNotificationSubscriptionsQueryOptions(browserApi),
    enabled
  });
  const items = subscriptions.data?.items ?? [];

  const toggle = useMutation({
    mutationFn: ({
      targetType,
      targetId,
      follow
    }: {
      targetType: FollowTargetType;
      targetId: string;
      follow: boolean;
    }) => {
      const params = { path: { target_type: targetType, target_id: targetId } };
      return follow
        ? unwrap(
            browserApi.PUT(
              "/api/v1/api-keys/notification-subscriptions/{target_type}/{target_id}",
              { params }
            )
          )
        : unwrap(
            browserApi.DELETE(
              "/api/v1/api-keys/notification-subscriptions/{target_type}/{target_id}",
              { params }
            )
          );
    },
    onSuccess: (updated: Subscriptions) => {
      queryClient.setQueryData(API_KEY_SUBSCRIPTIONS_KEY, updated);
      void invalidateExpiringApiKeys(queryClient);
    },
    onError: (error) => toastApiError(error, t)
  });

  return {
    follows: (targetType: FollowTargetType, targetId: string) =>
      items.some((item) => item.target_type === targetType && item.target_id === targetId),
    toggle
  };
}
