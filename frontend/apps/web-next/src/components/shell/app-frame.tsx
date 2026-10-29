"use client";

import {
  QueryAppContextProvider,
  type AppContextEnv
} from "@/components/providers/app-context-from-queries";
import { JobsProvider } from "@/features/jobs/use-jobs";
import { TourProvider } from "@/features/whats-new/tour-provider";
import { AppShellFrame } from "./app-shell";

/** The signed-in provider tree stays mounted as pages and release markers change. */
export function AppFrame({
  env,
  sideNavCollapsed,
  children
}: {
  env: AppContextEnv;
  sideNavCollapsed: boolean;
  children: React.ReactNode;
}) {
  return (
    <QueryAppContextProvider env={env}>
      <TourProvider>
        <JobsProvider>
          <AppShellFrame sideNavCollapsed={sideNavCollapsed}>{children}</AppShellFrame>
        </JobsProvider>
      </TourProvider>
    </QueryAppContextProvider>
  );
}
