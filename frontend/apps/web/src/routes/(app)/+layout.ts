import { createZitadelClient } from "$lib/core/Zitadel";
import { createEneo, createEneoSocket } from "@eneo/eneo-js";

export const load = async (event) => {
  event.depends("global:state");

  const { tokens, environment, featureFlags } = event.data;

  const eneo = createEneo({
    token: tokens.id_token,
    baseUrl: environment.baseUrl ?? "",
    fetch: event.fetch
  });

  let zitadelClient: ReturnType<typeof createZitadelClient> | null = null;
  if (environment.authUrl && event.data.tokens.access_token) {
    zitadelClient = createZitadelClient(
      environment.authUrl,
      event.data.tokens.access_token,
      event.fetch
    );
  }

  const eneoSocket = createEneoSocket(
    {
      token: event.data.tokens.id_token,
      baseUrl: environment.baseUrl ?? ""
    },
    {
      defaultSubscriptions: ["app_run_updates"]
    }
  );

  const getUserInfo = async () => {
    if (zitadelClient) {
      try {
        const [userInfo, usesIdp] = await Promise.all([
          zitadelClient.getUserInfo(),
          zitadelClient.getNumOfLinkedIdps().then((num) => num > 0)
        ]);
        return { ...userInfo, usesIdp };
      } catch (e) {
        console.error("Couldnt get user info, maybe URL not allowed?");
      }
    }
    return null;
  };

  const [userInfo, user, tenant, backendVersion, limits, settings] = await Promise.all([
    getUserInfo(),
    eneo.users.me(),
    eneo.users.tenant(),
    eneo.version.get(),
    eneo.limits.list(),
    eneo.settings.get()
  ]);

  const versions = {
    frontend: environment.frontendVersion,
    backend: backendVersion,
    client: eneo.client.version,
    gitInfo: environment.gitInfo
  };

  return {
    eneo,
    eneoSocket,
    zitadelClient,
    user,
    userInfo: userInfo ?? {
      firstName: user.email,
      lastName: user.email,
      displayName: user.email,
      usesIdp: false
    },
    tenant,
    versions,
    limits,
    settings,
    featureFlags,
    environment
  };
};
