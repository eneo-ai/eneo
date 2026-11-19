"use strict";

window.addEventListener("load", function () {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    presets: [SwaggerUIBundle.presets.apis],
    layout: "BaseLayout",
    deepLinking: true,
    displayRequestDuration: true,
    persistAuthorization: false,
    queryConfigEnabled: false,
    validatorUrl: null,
    withCredentials: false,
    requestInterceptor: function (request) {
      // Manual API-key requests must not borrow the browser's Eneo session.
      request.credentials = "omit";
      if (new URL(request.url, window.location.href).origin !== window.location.origin) {
        throw new Error("API documentation requests must stay on this Eneo origin");
      }
      return request;
    },
  });
});
