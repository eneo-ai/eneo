import { Header } from "@/components/shell/header";

export default function AppLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="flex min-h-svh flex-col">
      <Header />
      <div className="flex flex-1">
        {/* Sidebar placeholder; navigation lands in Phase 4. */}
        <aside className="bg-sidebar hidden w-56 border-r md:block" />
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
