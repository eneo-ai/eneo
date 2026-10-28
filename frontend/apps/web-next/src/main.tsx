import { config as configureZod } from "zod";
import { loadMessages, readCspNonce, resolveLocale, showBootError } from "./boot";
import { loadRuntimeConfig, setRuntimeConfig } from "./lib/runtime-config";
import "./app/globals.css";

const locale = resolveLocale(document);
const messages = loadMessages(locale);
const config = loadRuntimeConfig();
document.documentElement.lang = locale;
const nonce = readCspNonce();
globalThis.__webpack_nonce__ = nonce;
// Strict CSP forbids eval. Skip Zod's compilation probe before UI schemas run.
configureZod({ jitless: true });

const root = document.getElementById("root")!;
void Promise.all([messages, config])
  .then(async ([messages, config]) => {
    setRuntimeConfig(config);
    // UI modules may inject styles or parse schemas as soon as they evaluate.
    const { renderApp } = await import("./render-app");
    renderApp(root, { locale, messages, nonce });
  })
  .catch(() => showBootError(root));
