const mobileRegex = /Mobile|iP(hone|od|ad)|Android|BlackBerry|IEMobile/;
export function detectMobile(userAgent: string): boolean {
  return mobileRegex.test(userAgent);
}
