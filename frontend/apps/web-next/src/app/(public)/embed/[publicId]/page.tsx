import type { Metadata } from "next";
import {
  EmbedRoute,
  embedMetadata,
  type EmbedRouteProps
} from "@/features/widget/server/embed-route";

export const dynamic = "force-dynamic";

export function generateMetadata(props: EmbedRouteProps): Promise<Metadata> {
  return embedMetadata(props, "sv");
}

export default function Page(props: EmbedRouteProps) {
  return <EmbedRoute {...props} pathLocale="sv" />;
}
