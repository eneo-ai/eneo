import DocsShell from "@/components/DocsShell";
import { splitDocsPath } from "@/lib/languages";

export { metadata } from "@/components/DocsShell";

export default async function RootLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ mdxPath?: string[] }>;
}) {
  const { mdxPath = [] } = await params;
  const { language, page } = splitDocsPath(`/${mdxPath.join("/")}`);
  return (
    <DocsShell language={language} page={page}>
      {children}
    </DocsShell>
  );
}
