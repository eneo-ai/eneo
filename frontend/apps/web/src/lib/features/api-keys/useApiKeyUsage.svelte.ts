import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
import type { ApiKeyUsageResponse } from "./apiKeyTableUtils";

type GetUsageFn = (params: {
  id: string;
  limit: number;
  cursor?: string;
}) => Promise<ApiKeyUsageResponse>;

/**
 * Composable that encapsulates usage-loading state shared by both the user
 * and admin API key tables. Pass `getUsageFn` to select the right endpoint.
 */
export function useApiKeyUsage(getUsageFn: GetUsageFn) {
  let usageByKey = $state<Record<string, ApiKeyUsageResponse>>({});
  let usageErrorByKey = $state<Record<string, string | null>>({});
  let usageLoadingByKey = $state<Record<string, boolean>>({});
  let usageCursorByKey = $state<Record<string, string | null>>({});
  let activeTabByKey = $state<Record<string, "overview" | "usage">>({});

  function setActiveTab(id: string, tab: "overview" | "usage") {
    activeTabByKey = { ...activeTabByKey, [id]: tab };
    if (tab === "usage") {
      void loadUsage(id, { reset: false });
    }
  }

  async function loadUsage(id: string, { reset }: { reset: boolean }) {
    if (usageLoadingByKey[id]) return;
    if (!reset && usageByKey[id]) return;

    usageLoadingByKey = { ...usageLoadingByKey, [id]: true };
    usageErrorByKey = { ...usageErrorByKey, [id]: null };
    try {
      const response = await getUsageFn({ id, limit: 25 });
      usageByKey = { ...usageByKey, [id]: response };
      usageCursorByKey = { ...usageCursorByKey, [id]: response?.next_cursor ?? null };
    } catch (error) {
      console.error(error);
      usageErrorByKey = { ...usageErrorByKey, [id]: getErrorMessage(error) };
    } finally {
      usageLoadingByKey = { ...usageLoadingByKey, [id]: false };
    }
  }

  async function loadMoreUsage(id: string) {
    const cursor = usageCursorByKey[id];
    if (!cursor || usageLoadingByKey[id]) return;

    usageLoadingByKey = { ...usageLoadingByKey, [id]: true };
    usageErrorByKey = { ...usageErrorByKey, [id]: null };
    try {
      const response = await getUsageFn({ id, limit: 25, cursor });
      const existing = usageByKey[id];
      usageByKey = {
        ...usageByKey,
        [id]: {
          ...response,
          summary: existing?.summary ?? response.summary,
          items: [...(existing?.items ?? []), ...(response?.items ?? [])]
        }
      };
      usageCursorByKey = { ...usageCursorByKey, [id]: response?.next_cursor ?? null };
    } catch (error) {
      console.error(error);
      usageErrorByKey = { ...usageErrorByKey, [id]: getErrorMessage(error) };
    } finally {
      usageLoadingByKey = { ...usageLoadingByKey, [id]: false };
    }
  }

  return {
    get usageByKey() {
      return usageByKey;
    },
    get usageErrorByKey() {
      return usageErrorByKey;
    },
    get usageLoadingByKey() {
      return usageLoadingByKey;
    },
    get usageCursorByKey() {
      return usageCursorByKey;
    },
    get activeTabByKey() {
      return activeTabByKey;
    },
    setActiveTab,
    loadUsage,
    loadMoreUsage
  };
}
