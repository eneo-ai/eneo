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
      <div className="flex min-h-svh flex-col">
        <Header />
        <main className="flex flex-1 flex-col">{children}</main>
      </div>
    </AppContextProvider>
  );
}
