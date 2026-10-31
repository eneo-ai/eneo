const LAST_TENANT_KEY = "eneo-last-tenant-slug";

export function rememberedTenant() {
  try {
    return { available: true, slug: sessionStorage.getItem(LAST_TENANT_KEY) };
  } catch {
    return { available: false, slug: null };
  }
}

export function rememberTenant(slug: string): boolean {
  try {
    sessionStorage.setItem(LAST_TENANT_KEY, slug);
    return true;
  } catch {
    return false;
  }
}

export function forgetTenant() {
  try {
    sessionStorage.removeItem(LAST_TENANT_KEY);
  } catch {
    // The explicit chooser remains usable when storage is blocked.
  }
  try {
    // Production Svelte's chooser remembers its selection on the same origin.
    localStorage.removeItem("eneo:last-tenant");
  } catch {
    // Storage availability must not prevent an organisation switch.
  }
}
