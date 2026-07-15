import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiKeysList = vi.hoisted(() => vi.fn());
const spacesList = vi.hoisted(() => vi.fn());
const spacesListApplications = vi.hoisted(() => vi.fn());
const forceRefreshExpiringStore = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/AppContext.js", () => ({
  getAppContext: () => ({
    user: {
      id: "user-1",
      hasPermission: (permission: string) => permission === "api_keys"
    },
    tenant: {
      id: "tenant-1"
    },
    state: {
      userInfo: {
        subscribe: (run: (value: { firstName: string }) => void) => {
          run({ firstName: "Ada" });
          return () => {};
        }
      }
    }
  })
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    apiKeys: {
      list: apiKeysList
    },
    spaces: {
      list: spacesList,
      listApplications: spacesListApplications
    }
  })
}));

vi.mock("$lib/features/api-keys/expiringKeysStore", () => ({
  getExpiringKeysStore: () => ({
    forceRefresh: forceRefreshExpiringStore
  })
}));

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, unknown>>(
    {},
    {
      get: (_target, key) => {
        const label = String(key);
        return (params?: Record<string, unknown>) =>
          params ? `${label} ${JSON.stringify(params)}` : label;
      }
    }
  )
}));

vi.mock("$lib/features/api-keys/CreateApiKeyDialog.svelte", async () => ({
  default: (
    await import("../../../../../tests/fixtures/api-key-page/CreateApiKeyDialogStub.svelte")
  ).default
}));

vi.mock("./ApiKeyTable.svelte", async () => ({
  default: (await import("../../../../../tests/fixtures/api-key-page/ApiKeyTableStub.svelte"))
    .default
}));

vi.mock("$lib/features/api-keys/NotificationPreferences.svelte", async () => ({
  default: (
    await import("../../../../../tests/fixtures/api-key-page/NotificationPreferencesStub.svelte")
  ).default
}));

vi.mock("$lib/features/api-keys/ExpiringKeysBanner.svelte", async () => ({
  default: (
    await import("../../../../../tests/fixtures/api-key-page/ExpiringKeysBannerStub.svelte")
  ).default
}));

vi.mock("$lib/features/api-keys/ApiKeySecretDialog.svelte", async () => ({
  default: (
    await import("../../../../../tests/fixtures/api-key-page/ApiKeySecretDialogStub.svelte")
  ).default
}));

import ApiKeysPage from "./+page.svelte";

describe("account API keys page", () => {
  beforeEach(() => {
    apiKeysList.mockResolvedValue({ items: [], next_cursor: null });
    spacesList.mockResolvedValue([]);
    spacesListApplications.mockResolvedValue({ assistants: { items: [] }, apps: { items: [] } });
    forceRefreshExpiringStore.mockResolvedValue(undefined);
  });

  it("shows the empty state when no v2 API keys exist", async () => {
    render(ApiKeysPage);

    await expect.element(page.getByText("api_keys_your_keys")).toBeVisible();
    await expect.element(page.getByText("api_keys_description")).toBeVisible();
    await expect.element(page.getByTestId("api-key-table")).toHaveTextContent("0 keys");
  });
});
