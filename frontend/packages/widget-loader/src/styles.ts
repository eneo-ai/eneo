/**
 * Where the panel becomes a modal dialog: a phone, or a viewport
 * too short for the floating panel, such as a laptop zoomed to 200 %. In `em`
 * so a larger default font size switches earlier. On wider screens the chat's
 * header can ask for the same layout; see `:host([expanded])` below.
 */
export const FULL_SCREEN_MEDIA = "(max-width: 40em), (max-height: 31.25em)";

/**
 * Styles for the launcher and panel inside the shadow root. The build emits
 * this as eneo.css beside the loader, so hosts can allow it through style-src.
 * Host pages tune it through the `--eneo-widget-*` custom properties documented
 * in the README; nothing here leaks into or depends on the host's stylesheet.
 */
export const styles = `
:host {
  position: fixed;
  inset-block-end: var(--eneo-widget-offset-y, 20px);
  inset-inline-end: var(--eneo-widget-offset-x, 20px);
  z-index: var(--eneo-widget-z, 2147483000);
  display: block;
  font-family: system-ui, sans-serif;
  line-height: 1;
}
:host([hidden]) { display: none; }
:host([position="bottom-left"]) {
  inset-inline-end: auto;
  inset-inline-start: var(--eneo-widget-offset-x, 20px);
}
.launcher {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  /* Transparent, so forced colours (Windows contrast themes) draw a ring. */
  border: 2px solid transparent;
  border-radius: 50%;
  background: var(--eneo-widget-color, var(--_eneo-accent, #1d4ed8));
  color: var(--eneo-widget-on-color, var(--_eneo-on-accent, #ffffff));
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
  transition: transform 0.15s ease;
}
.launcher:hover { transform: scale(1.05); }
.launcher:focus-visible {
  outline: 3px solid var(--eneo-widget-on-color, var(--_eneo-on-accent, #ffffff));
  outline-offset: 2px;
  box-shadow: 0 0 0 6px var(--eneo-widget-color, var(--_eneo-accent, #1d4ed8));
}
.launcher[hidden] { display: none; }
/* Both icons sit on top of each other and cross-fade with a quarter turn. */
.launcher svg {
  position: absolute;
  inset: 0;
  margin: auto;
  width: 28px;
  height: 28px;
}
/* Transitions switch on at the first open (see openPanel): a stylesheet that
   arrives after the elements are in the tree would otherwise animate its own
   resting state, e.g. fade the backdrop out on page load. */
.launcher.motion svg { transition: opacity 0.15s ease, transform 0.15s ease; }
.launcher .close { opacity: 0; transform: rotate(-90deg); }
:host([open]) .launcher .chat { opacity: 0; transform: rotate(90deg); }
:host([open]) .launcher .close { opacity: 1; transform: none; }
.badge {
  position: absolute;
  inset-block-start: -4px;
  inset-inline-end: -4px;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: #b91c1c;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  line-height: 20px;
  text-align: center;
  box-sizing: border-box;
}
.badge[hidden] { display: none; }
.panel {
  position: absolute;
  inset-block-end: 72px;
  inset-inline-end: 0;
  width: min(400px, calc(100vw - 40px));
  height: min(700px, calc(100vh - 112px));
  border-radius: var(--eneo-widget-radius, 16px);
  overflow: hidden;
  background: #ffffff;
  color: #111111;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
  opacity: 0;
  transform-origin: bottom right;
  transform: translateY(12px) scale(0.94);
  transition: opacity 0.22s cubic-bezier(0.2, 0.8, 0.2, 1), transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.panel.open { opacity: 1; transform: none; }
:host([position="bottom-left"]) .panel { transform-origin: bottom left; }
.panel[hidden] { display: none; }
/* The backdrop is always in the tree on small screens, so it can fade. */
.backdrop, .loading-close { display: none; }
.loading-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 24px;
  line-height: 1.5;
}
.loading-state p { margin: 0; font-size: 14px; }
.loading-indicator {
  width: 24px;
  height: 24px;
  box-sizing: border-box;
  border: 2px solid currentColor;
  border-inline-end-color: transparent;
  border-radius: 50%;
  opacity: 0.6;
  animation: eneo-spin 1s linear infinite;
}
@keyframes eneo-spin { to { transform: rotate(360deg); } }
:host(:not([loaded]):not([ready])) iframe { visibility: hidden; opacity: 0; }
:host([loaded]) .loading-state, :host([ready]) .loading-state { display: none; }
:host([position="bottom-left"]) .panel { inset-inline-end: auto; inset-inline-start: 0; }
:host([color-scheme="dark"]) .panel { background: #111111; color: #f5f5f5; }
@supports (height: 100dvh) {
  .panel { height: min(700px, calc(100dvh - 112px)); }
}
@media (prefers-color-scheme: dark) {
  :host(:not([color-scheme="light"])) .panel { background: #111111; color: #f5f5f5; }
}
@media ${FULL_SCREEN_MEDIA} {
  .backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.3);
    overscroll-behavior: contain;
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
  }
  .backdrop.motion { transition: opacity 0.2s ease, visibility 0.2s; }
  :host([open]) .backdrop { opacity: 1; visibility: visible; pointer-events: auto; }
  .panel {
    display: flex;
    flex-direction: column;
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    border-radius: 0;
    opacity: 1;
    transform-origin: center;
    transform: translateY(100%);
    transition: transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1);
    overscroll-behavior: contain;
  }
  .panel.open { transform: none; }
  :host([open]) .launcher { display: none; }
  /* A separate, reserved row stays reachable even if the iframe never
     loads. Once ready, the chat's own header owns the close control. */
  :host(:not([ready])) .loading-close {
    display: flex;
    flex: 0 0 48px;
    align-items: center;
    justify-content: flex-end;
    padding-inline: 12px;
  }
  .loading-state { inset-block-start: 48px; }
  .loading-close button {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    box-sizing: border-box;
    border: 2px solid transparent;
    border-radius: 50%;
    background: transparent;
    color: inherit;
    cursor: pointer;
  }
  .loading-close svg { width: 24px; height: 24px; }
  .loading-close button:focus-visible {
    outline: 2px solid currentColor;
    outline-offset: -4px;
  }
  .panel iframe { flex: 1; min-height: 0; height: 0; }
}
@media (max-width: 40em) {
  .panel {
    --_eneo-sheet-gap: min(24px, 4svh);
    inset-block-start: var(--_eneo-sheet-gap);
    height: calc(100% - var(--_eneo-sheet-gap));
    border-radius: 20px 20px 0 0;
  }
}
/* Expanded from the chat's own header on a wide screen: the same full-viewport
   panel. Only a running chat can ask, and its header closes the panel, so the
   launcher is not needed as a way out. */
:host([expanded]) .panel {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  border-radius: 0;
}
:host([expanded]) .launcher { display: none; }
@media (prefers-reduced-motion: reduce) {
  .launcher, .launcher.motion svg, .panel, .backdrop.motion, iframe { transition: none; }
  .loading-indicator { animation: none; }
  .launcher:hover { transform: none; }
}
iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  transition: opacity 0.18s ease;
}
`;
