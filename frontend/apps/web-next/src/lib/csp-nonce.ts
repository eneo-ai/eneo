declare global {
  // get-nonce reads this global for third-party injected styles.
  var __webpack_nonce__: string | undefined;
}

export function readCspNonce(): string | undefined {
  // Browsers hide the nonce content attribute; the DOM property remains readable.
  return document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce || undefined;
}
