import { createContext } from "$lib/core/context";
import type { Role, UserGroup } from "@eneo/eneo-js";

import type { AvailablePasswordChangeCapability } from "$lib/features/auth/passwordChange";

type AdminUserCtx = {
  passwordCapability: AvailablePasswordChangeCapability;
  userGroups: UserGroup[];
  roles: Role[];
};

export const [getAdminUserCtx, setAdminUserCtx] = createContext<AdminUserCtx>();
