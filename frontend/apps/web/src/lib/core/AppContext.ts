import { hasPermission } from "$lib/core/hasPermission";
import { writable } from "svelte/store";
import { createContext } from "./context";
import type { CurrentUser, Limits, Tenant, Settings } from "@intric/intric-js";
import type { createZitadelClient } from "$lib/core/Zitadel";

const [getAppContext, setAppContext] = createContext<ReturnType<typeof AppContext>>(
  "Context for app-wide data"
);

function initAppContext(data: AppContextParams) {
  setAppContext(AppContext(data));
}

export type UserInfo = {
  firstName: string;
  lastName: string;
  displayName: string;
};

type AppContextParams = {
  user: CurrentUser;
  userInfo: UserInfo & { usesIdp: boolean };
  zitadelClient: ReturnType<typeof createZitadelClient> | null;
  tenant: Tenant;
  limits: Limits;
  settings: Settings;
  versions: {
    frontend: string;
    backend: string;
    client: string;
    preview?: { branch?: string; commit?: string };
  };
  featureFlags: App.Locals["featureFlags"];
  environment: App.Locals["environment"];
};

function AppContext(data: AppContextParams) {
  const user = { ...data.user, hasPermission: hasPermission(data.user) };
  const showHeader = writable(true);
  const userInfo = writable(data.userInfo);

  async function updateUserInfo(update: UserInfo) {
    if (data.zitadelClient) {
      if (update.displayName === "") {
        update.displayName = `${update.firstName} ${update.lastName}`;
      }
      const success = await data.zitadelClient.updateUserInfo(update);
      if (success) {
        userInfo.update((info) => {
          info.firstName = update.firstName;
          info.lastName = update.lastName;
          info.displayName = update.displayName;
          return info;
        });
        return;
      }
    }
    throw new Error("Error updating user info");
  }

  return Object.freeze({
    user,
    tenant: data.tenant,
    limits: data.limits,
    settings: data.settings,
    versions: data.versions,
    featureFlags: data.featureFlags,
    environment: data.environment,
    /** Update the user's name. */
    updateUserInfo,
    state: {
      /** User's name. Eventhough this is a store it's currently not being used as such. Read more in AppContext.ts */
      userInfo,
      showHeader
    }
  });
}

export { initAppContext, getAppContext };
