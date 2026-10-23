/**
 * The Eneo theme's name (`name` in src/theme/eneo-theme.ts), for the server:
 * the root layout puts it on <html> as the Astryx theme scope before any
 * client code runs. The built theme module (src/theme/eneo.js) is client-only
 * since Astryx 0.7.3 (it reads the Neutral theme's icons through a client
 * barrel), so the server never imports it; eneo-theme.contrast.test.ts checks
 * that this name is the theme's.
 */
export const ENEO_THEME_NAME = "eneo";
