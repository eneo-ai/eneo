import { routeTitle } from "@/lib/route-head";

/** Match the module handoff's FastAPI response policy in document metadata. */
export function moduleLoginHead(key: string) {
  const titled = routeTitle(key);
  return (context: Parameters<typeof titled>[0]) => ({
    meta: [
      ...titled(context).meta,
      { name: "robots", content: "noindex, nofollow, noarchive" },
      { name: "referrer", content: "no-referrer" }
    ]
  });
}
