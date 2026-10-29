import { importPage } from "nextra/pages";
import { notFound } from "next/navigation";
import { getSourceRoutes, resolveContent } from "@/lib/content";
import { publishedRoutes } from "@/lib/languages";
import { useMDXComponents as getMDXComponents } from "../../mdx-components";

type Props = { params: Promise<{ mdxPath?: string[] }> };

export async function generateStaticParams() {
  return publishedRoutes([...(await getSourceRoutes())]).map((route) => ({
    mdxPath: route.split("/").filter(Boolean),
  }));
}

export async function generateMetadata({ params }: Props) {
  const content = await resolveContent((await params).mdxPath);
  if (!(await getSourceRoutes()).has(content.page)) notFound();
  const { metadata } = await importPage(
    content.source.split("/").filter(Boolean),
  );
  return {
    ...metadata,
    // A fallback is a reading aid, never a second copy in search engines.
    ...(content.fallback ? { robots: { index: false, follow: true } } : {}),
  };
}

const Wrapper = getMDXComponents().wrapper;

export default async function Page(props: Props) {
  const params = await props.params;
  const content = await resolveContent(params.mdxPath);
  if (!(await getSourceRoutes()).has(content.page)) notFound();
  const {
    default: MDXContent,
    toc,
    metadata,
  } = await importPage(content.source.split("/").filter(Boolean));
  return (
    <Wrapper
      toc={toc}
      metadata={metadata}
      data-pagefind-ignore={content.fallback ? "all" : undefined}
    >
      {content.fallback && (
        <aside
          className="my-6 rounded-lg border border-amber-400 bg-amber-50 p-4 text-gray-900 dark:bg-neutral-900 dark:text-gray-100"
          aria-label="Översättning saknas"
          data-pagefind-ignore="all"
        >
          Den här sidan är inte översatt till svenska för den valda versionen.
          Nedan visas den engelska originaltexten. Den ingår bara i den engelska
          sökningen.{" "}
          <a
            className="underline"
            href={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}${content.page}`}
            lang="en"
          >
            Read in English
          </a>
        </aside>
      )}
      <div lang={content.fallback ? "en" : content.language}>
        <MDXContent {...props} params={params} />
      </div>
    </Wrapper>
  );
}
