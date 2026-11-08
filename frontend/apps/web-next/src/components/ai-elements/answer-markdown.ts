import { defaultRehypePlugins, defaultRemarkPlugins } from "streamdown";

// Keep Streamdown's GFM and sanitize/harden defaults in both the interactive
// answer and its clipboard representation. Math runs after sanitization.
export const answerRemarkPlugins = Object.values(defaultRemarkPlugins);
export const answerRehypePlugins = Object.values(defaultRehypePlugins);
