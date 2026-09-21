/**
 * Styles for the launcher and panel inside the shadow root. Host pages tune
 * them through the `--eneo-widget-*` custom properties documented in the
 * README; nothing here leaks into or depends on the host's stylesheet.
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
  margin: 0;
  padding: 0;
  border: 0;
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
.launcher svg { width: 28px; height: 28px; }
.launcher .close { display: none; }
:host([open]) .launcher .chat { display: none; }
:host([open]) .launcher .close { display: block; }
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
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
  opacity: 0;
  transform: translateY(8px) scale(0.98);
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.panel.open { opacity: 1; transform: none; }
.panel[hidden] { display: none; }
:host([position="bottom-left"]) .panel { inset-inline-end: auto; inset-inline-start: 0; }
:host([color-scheme="dark"]) .panel { background: #111111; }
@supports (height: 100dvh) {
  .panel { height: min(700px, calc(100dvh - 112px)); }
}
@media (prefers-color-scheme: dark) {
  :host(:not([color-scheme="light"])) .panel { background: #111111; }
}
@media (max-width: 639px) {
  .panel {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    border-radius: 0;
  }
  /* The chat's own header closes the panel once the embed page is ready.
     Until then (loading, a paused notice, a page that never loads) the
     launcher stays on top of the full-screen panel as the way out. */
  :host([open]) .launcher { z-index: 1; }
  :host([open][ready]) .launcher { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .launcher, .panel { transition: none; }
  .launcher:hover { transform: none; }
}
iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}
`;
