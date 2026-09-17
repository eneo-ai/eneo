import { installApi } from "./api";
import { mountFromScript, resolveOrigin } from "./bootstrap";
import { EneoWidgetElement } from "./element";

const script = document.currentScript as HTMLScriptElement | null;
EneoWidgetElement.defaultBaseUrl = resolveOrigin(script, location.origin);

if (!customElements.get("eneo-widget")) {
  customElements.define("eneo-widget", EneoWidgetElement);
}
installApi(window, __LOADER_VERSION__);
if (script) mountFromScript(script);
