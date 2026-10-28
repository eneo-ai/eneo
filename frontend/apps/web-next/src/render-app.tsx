import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createTranslator } from "use-intl";
import { BootContext, type Boot } from "./boot-context";
import { RootErrorBoundary } from "./components/shell/root-error-boundary";
import { getQueryClient } from "./lib/api/query";
import { createAppRouter } from "./router";

export function renderApp(root: HTMLElement, boot: Boot): void {
  const router = createAppRouter({
    queryClient: getQueryClient(),
    t: createTranslator({ locale: boot.locale, messages: boot.messages })
  });
  createRoot(root).render(
    <RootErrorBoundary>
      <StrictMode>
        <BootContext value={boot}>
          <RouterProvider router={router} />
        </BootContext>
      </StrictMode>
    </RootErrorBoundary>
  );
}
