import { createContext } from "$lib/core/context";
import type { Role, UserGroup } from "@intric/intric-js";

type AdminUserCtx = {
  userGroups: UserGroup[];
  roles: Role[];
};

export const [getAdminUserCtx, setAdminUserCtx] = createContext<AdminUserCtx>();
