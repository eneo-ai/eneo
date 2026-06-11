import { Header } from "@/components/shell/header";
import { requireSession } from "@/lib/auth/session";

export default async function AppLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const session = await requireSession();

  return (
    <div className="flex min-h-svh flex-col">
      <Header userEmail={session.user.email} />
      <div className="flex flex-1">
        {/* Sidebar placeholder; navigation lands in Phase 4. */}
        <aside className="bg-sidebar hidden w-56 border-r md:block" />
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
