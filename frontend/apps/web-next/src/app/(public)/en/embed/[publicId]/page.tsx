import type { Metadata } from "next";
import {
  EmbedRoute,
  embedMetadata,
  type EmbedRouteProps
} from "@/features/widget/server/embed-route";

export const dynamic = "force-dynamic";

/** The English embed page, at the path the loader builds for `lang="en"`. */
export function generateMetadata(props: EmbedRouteProps): Promise<Metadata> {
  return embedMetadata(props, "en");
}

export default function Page(props: EmbedRouteProps) {
  return <EmbedRoute {...props} pathLocale="en" />;
}
