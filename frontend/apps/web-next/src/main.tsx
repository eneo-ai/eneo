import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createTranslator } from "use-intl";
import { BootContext } from "./boot-context";
import { getQueryClient } from "./lib/api/query";
import { defaultLocale } from "./lib/i18n/locales";
import { createAppRouter } from "./router";
import "./app/globals.css";

// The Vite build's entry. P4-index-html-boot completes the boot: the locale
// from <html lang> or the locale cookie, the runtime config loaded beside the
// catalogue, the CSP nonce, the bilingual boot error and the outermost error
// boundary.
const locale = defaultLocale;

void import(`./lib/i18n/messages/${locale}.json`).then(({ default: messages }) => {
  const router = createAppRouter({
    queryClient: getQueryClient(),
    t: createTranslator({ locale, messages })
  });

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <BootContext value={{ locale, messages, nonce: undefined }}>
        <RouterProvider router={router} />
      </BootContext>
    </StrictMode>
  );
});
