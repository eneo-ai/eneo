// MCP Apps sandbox proxy protocol, following the official basic-host pattern.
// This is trusted transport glue only; AppBridge/App own the RPC protocol.
(() => {
  "use strict";
  const hostOrigin = __HOST_ORIGIN__;
  if (!hostOrigin || window.parent === window || location.origin === hostOrigin)
    return;
  let inner;
  let loaded = false;
  let revoked = false;
  const prefix = "ui/notifications/sandbox-";
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;
    if (event.source === window.parent && event.origin === hostOrigin) {
      if (message.method === "ui/notifications/sandbox-resource-ready") {
        if (inner || typeof message.params?.html !== "string") return;
        inner = document.createElement("iframe");
        inner.title = "MCP App";
        // Never accept a server-supplied sandbox override. The child must be
        // opaque: it cannot edit this trusted proxy or its inherited CSP.
        inner.setAttribute("sandbox", "allow-scripts");
        inner.referrerPolicy = "no-referrer";
        if (message.params.permissions?.clipboardWrite) {
          inner.allow = "clipboard-write";
        }
        inner.onload = () => {
          if (loaded) revoked = true;
          loaded = true;
        };
        // srcdoc inherits our HTTP CSP. frame-src 'none' on THIS parent
        // blocks child self-navigation before a request can leak its data.
        inner.srcdoc = message.params.html;
        document.body.appendChild(inner);
      } else if (!revoked && !message.method?.startsWith(prefix)) {
        inner?.contentWindow?.postMessage(message, "*");
      }
    } else if (
      !revoked &&
      inner &&
      event.source === inner.contentWindow &&
      event.origin === "null"
    ) {
      // An app may not impersonate this proxy's lifecycle notifications.
      if (!message.method?.startsWith(prefix))
        window.parent.postMessage(message, hostOrigin);
    }
  });
  window.addEventListener(
    "load",
    () => {
      window.parent.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/sandbox-proxy-ready",
          params: {},
        },
        hostOrigin,
      );
    },
    { once: true },
  );
})();
