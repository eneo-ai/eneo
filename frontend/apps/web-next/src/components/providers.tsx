"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { getQueryClient } from "@/lib/api/query";

export function Providers({ children }: { children: React.ReactNode }) {
  // getQueryClient (not useState): a stable client that survives suspense
  // re-renders without being recreated, per the TanStack SSR guide.
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
