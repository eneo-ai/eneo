import { AppContextProvider, type AppContextData } from "@/components/providers/app-context";
import { Header } from "@/components/shell/header";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import packageJson from "../../../package.json";

export default async function AppLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const api = eneoApi();
  const [user, tenant, settings, limits, backendVersion] = await Promise.all([
    unwrap(api.GET("/api/v1/users/me/")),
    unwrap(api.GET("/api/v1/users/tenant/")),
    unwrap(api.GET("/api/v1/settings/")),
    unwrap(api.GET("/api/v1/limits/")),
    // The spec types /version as unknown; it returns a bare string.
    unwrap(api.GET("/version")).then((version) => (typeof version === "string" ? version : ""))
  ]);

  const value: AppContextData = {
    user,
    tenant,
    settings,
    limits,
    versions: { frontend: packageJson.version, backend: backendVersion }
  };

  return (
    <AppContextProvider value={value}>
      {/* Viewport-locked shell: pages scroll inside main, so full-height
          surfaces (chat) can pin their input to the bottom. */}
      <div className="flex h-svh flex-col">
        <Header />
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
      </div>
    </AppContextProvider>
  );
}
