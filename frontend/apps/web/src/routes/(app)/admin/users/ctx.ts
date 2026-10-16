import { createContext } from "$lib/core/context";
import type { PasswordLifecyclePolicy, Role, UserGroup } from "@eneo/eneo-js";

import type { AvailablePasswordChangeCapability } from "$lib/features/auth/passwordChange";

type AdminUserCtx = {
  passwordCapability: AvailablePasswordChangeCapability;
  /** null when the policy could not be loaded; hints that depend on it stay quiet. */
  passwordLifecyclePolicy: PasswordLifecyclePolicy | null;
  userGroups: UserGroup[];
  roles: Role[];
};

export const [getAdminUserCtx, setAdminUserCtx] = createContext<AdminUserCtx>();
