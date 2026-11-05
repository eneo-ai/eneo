import { config as configureZod } from "zod";
import { loadMessages, readCspNonce, resolveLocale, showBootError } from "./boot";
import { loadRuntimeConfig, setRuntimeConfig } from "./lib/runtime-config";
import { initializeBrowserSession } from "./lib/api/refusal";
import { installChunkRecovery } from "./lib/chunk-recovery";
import "@/styles/globals.css";

installChunkRecovery();
const locale = resolveLocale(document);
const messages = loadMessages(locale);
const embed = /^(?:\/en)?\/embed\/[^/]+\/?$/.test(location.pathname);
const config = embed ? Promise.resolve(undefined) : loadRuntimeConfig();
document.documentElement.lang = locale;
const nonce = readCspNonce();
globalThis.__webpack_nonce__ = nonce;
// Strict CSP forbids eval. Skip Zod's compilation probe before UI schemas run.
configureZod({ jitless: true });

const root = document.getElementById("root")!;
void Promise.all([messages, config, embed ? undefined : initializeBrowserSession()])
  .then(async ([messages, config]) => {
    if (config) setRuntimeConfig(config);
    // UI modules may inject styles or parse schemas as soon as they evaluate.
    const { renderApp } = await import("./render-app");
    renderApp(root, { locale, messages, nonce });
  })
  .catch(() => showBootError(root));
