export const LoginErrorCode = {
  NO_VERIFIER: "Authentication session expired. Please ensure cookies are enabled and try again.",
  NO_TOKEN: "Failed to authenticate with Eneo. Please try again.",
  DECODE_ERROR: "Invalid authentication response received. Please try again.",
  NO_CONFIG: "Authentication service is not properly configured. Please contact your administrator.",
  INVALID_CREDENTIALS: "Invalid username or password. Please check your credentials.",
  USER_INACTIVE: "Your account is inactive. Please contact your administrator.",
  TENANT_SUSPENDED: "Your organization's access is suspended. Please contact your administrator.",
  NETWORK_ERROR: "Network error during authentication. Please check your connection and try again.",
  SERVER_ERROR: "Authentication service is temporarily unavailable. Please try again later."
} as const;

export const providers = ["zitadel", "mobilityguard", "oidc"] as const;

export class LoginError extends Error {
  code: keyof typeof LoginErrorCode;
  provider: (typeof providers)[number];
  constructor(
    provider: (typeof providers)[number],
    code: keyof typeof LoginErrorCode,
    message: string = ""
  ) {
    super(LoginErrorCode[code] + message);
    this.name = "LoginError";
    this.provider = provider;
    this.code = code;
  }

  getErrorShortCode() {
    return `${this.provider}_${this.code}`.toLowerCase();
  }

  static getMessageFromShortCode(code: string) {
    const splitIdx = code.indexOf("_");
    const provider = code.substring(0, 1).toUpperCase() + code.substring(1, splitIdx);
    const id = code.substring(splitIdx + 1).toUpperCase() as keyof typeof LoginErrorCode;
    return `${provider}: ${LoginErrorCode[id]}`;
  }
}
