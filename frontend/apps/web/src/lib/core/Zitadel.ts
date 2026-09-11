import type { UserInfo } from "$lib/core/AppContext";

export type ZitadelPasswordComplexityPolicy = Readonly<{
  minLength: number;
  hasUppercase: boolean;
  hasLowercase: boolean;
  hasNumber: boolean;
  hasSymbol: boolean;
}>;

export type ZitadelPasswordChangeCapability =
  | Readonly<{
      source: "zitadel";
      policy: ZitadelPasswordComplexityPolicy;
    }>
  | Readonly<{
      source: "external";
      policy: null;
    }>;

export class ZitadelRequestError extends Error {
  constructor(
    readonly operation: "capability" | "password_change",
    readonly status: number
  ) {
    super(`Zitadel ${operation} request failed with status ${status}`);
    this.name = "ZitadelRequestError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getRecord(parent: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = parent[key];
  if (!isRecord(value)) throw new ZitadelRequestError("capability", 502);
  return value;
}

function getBoolean(parent: Record<string, unknown>, key: string): boolean {
  const value = parent[key];
  if (typeof value !== "boolean") throw new ZitadelRequestError("capability", 502);
  return value;
}

function getNonNegativeInteger(parent: Record<string, unknown>, key: string): number {
  const raw = parent[key];
  const value = typeof raw === "string" && /^\d+$/.test(raw) ? Number(raw) : raw;
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new ZitadelRequestError("capability", 502);
  }
  return Number(value);
}

export function createZitadelClient(baseUrl: string, access_token: string, _fetch: typeof fetch) {
  const endpoint = (path: string) => `${baseUrl.replace(/\/$/, "")}${path}`;

  async function requestJson(path: string): Promise<Record<string, unknown>> {
    const response = await _fetch(endpoint(path), {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${access_token}`
      }
    });
    if (!response.ok) throw new ZitadelRequestError("capability", response.status);

    const body: unknown = await response.json().catch(() => null);
    if (!isRecord(body)) throw new ZitadelRequestError("capability", 502);
    return body;
  }

  return {
    /** A simple call to check if any idps are configured for this user */
    async getNumOfLinkedIdps() {
      try {
        const userEndpoint = baseUrl + "/auth/v1/users/me/idps/_search";
        const res = await _fetch(userEndpoint, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${access_token}`
          },
          body: JSON.stringify({ limit: 1 })
        });
        const json = await res.json();
        const numberOfIdps = json.details.totalResult ?? 0;
        return numberOfIdps as number;
      } catch (e) {
        console.error("Couldn't get idp info", e);
        return 0;
      }
    },

    async getUserInfo() {
      const userEndpoint = baseUrl + "/auth/v1/users/me/profile";
      const res = await _fetch(userEndpoint, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${access_token}`
        }
      });
      const json = await res.json();
      const userInfo = json.profile;
      if (userInfo === undefined) {
        throw new Error("No profile found!");
      }
      return userInfo as UserInfo;
    },

    async updateUserInfo(update: UserInfo) {
      const userEndpoint = baseUrl + "/auth/v1/users/me/profile";
      const res = await _fetch(userEndpoint, {
        method: "PUT",
        body: JSON.stringify(update),
        headers: {
          Authorization: `Bearer ${access_token}`
        }
      });

      if (res.ok) {
        return true;
      }

      throw new Error(`Status: ${res.status} - Text: ${await res.text()}`);
    },

    /**
     * Determine whether the signed-in human owns a local Zitadel password.
     * A linked external IdP is not sufficient evidence either way: users may
     * have both. The self-user password state and effective login policy are
     * the canonical capability signals.
     *
     * Any malformed or failed provider response throws so callers can fail
     * closed instead of silently presenting the wrong password owner.
     */
    async getPasswordChangeCapability(): Promise<ZitadelPasswordChangeCapability> {
      const [myUser, loginPolicy] = await Promise.all([
        requestJson("/auth/v1/users/me"),
        requestJson("/auth/v1/policies/login")
      ]);

      const user = getRecord(myUser, "user");
      const human = getRecord(user, "human");
      const login = getRecord(loginPolicy, "policy");
      const passwordChanged = human.passwordChanged;
      const ownsLocalPassword =
        typeof passwordChanged === "string" && passwordChanged.trim().length > 0;
      const allowsUsernamePassword = getBoolean(login, "allowUsernamePassword");

      if (!ownsLocalPassword || !allowsUsernamePassword) {
        return { source: "external", policy: null };
      }

      const complexityResponse = await requestJson("/auth/v1/policies/passwords/complexity");
      const policy = getRecord(complexityResponse, "policy");

      return {
        source: "zitadel",
        policy: {
          minLength: getNonNegativeInteger(policy, "minLength"),
          hasUppercase: getBoolean(policy, "hasUppercase"),
          hasLowercase: getBoolean(policy, "hasLowercase"),
          hasNumber: getBoolean(policy, "hasNumber"),
          hasSymbol: getBoolean(policy, "hasSymbol")
        }
      };
    },

    async updatePassword(oldPassword: string, newPassword: string): Promise<void> {
      const response = await _fetch(endpoint("/auth/v1/users/me/password"), {
        method: "PUT",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          Authorization: `Bearer ${access_token}`
        },
        body: JSON.stringify({ oldPassword, newPassword })
      });

      if (!response.ok) {
        throw new ZitadelRequestError("password_change", response.status);
      }
    }
  };
}
