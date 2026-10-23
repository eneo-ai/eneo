import { createZitadelClient } from "$lib/core/Zitadel";
import { createEneo, createEneoSocket } from "@eneo/eneo-js";
import { redirect } from "@sveltejs/kit";
import {
  handlePasswordChangeRequired,
  passwordChangeUrl
} from "$lib/features/auth/passwordChangeRequired";

export const load = async (event) => {
  event.depends("global:state");

  const { tokens, environment, featureFlags } = event.data;

  const eneo = createEneo({
    token: tokens.id_token,
    baseUrl: environment.baseUrl ?? "",
    fetch: event.fetch,
    onError: (error) => handlePasswordChangeRequired(error, event.url)
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

  // A session that must replace its local password is refused by every
  // endpoint here except /users/me/. The client's error handler also covers
  // later calls from the loaded app, when a policy changes or a password expires.
  const loaded = await Promise.all([
    getUserInfo(),
    eneo.users.me(),
    eneo.users.tenant(),
    eneo.version.get(),
    eneo.limits.list(),
    eneo.settings.get(),
    // Non-essential: an older backend during a rolling deploy must not block the app.
    eneo.whatsNew.getState().catch(() => null)
  ]);
  const [userInfo, user, tenant, backendVersion, limits, settings, whatsNewState] = loaded;
  if (user.password_status?.change_required) {
    redirect(302, passwordChangeUrl(event.url));
  }

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
    // undefined = could not be read (older backend, transient error): show
    // neither the dot nor the announcement rather than treating it as "never".
    whatsNewEnabled: settings.whats_new_enabled !== false,
    whatsNewVersion: versions.frontend,
    whatsNewSeenVersion: whatsNewState ? whatsNewState.seen_version : undefined,
    whatsNewAnnouncedVersion: whatsNewState ? whatsNewState.announced_version : undefined,
    featureFlags,
    environment
  };
};
