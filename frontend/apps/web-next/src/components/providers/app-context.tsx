"use client";

import { createContext, useContext, useMemo } from "react";
import type { Schema } from "@/lib/api/models";
import { hasPermission, type PermissionRequirement } from "@/lib/auth/permissions";

export type AppContextData = {
  user: Schema<"UserPublic">;
  tenant: Schema<"TenantPublic">;
  settings: Schema<"SettingsPublic">;
  limits: Schema<"Limits">;
  versions: { frontend: string; backend: string };
};

export type AppContextValue = AppContextData & {
  /** Tenant-level permission check from the user's flattened roles. */
  can: (required: PermissionRequirement) => boolean;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppContextProvider({
  value,
  children
}: {
  value: AppContextData;
  children: React.ReactNode;
}) {
  const context = useMemo<AppContextValue>(
    () => ({ ...value, can: hasPermission(value.user) }),
    [value]
  );
  return <AppContext.Provider value={context}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) throw new Error("useAppContext must be used inside the (app) layout");
  return context;
}
