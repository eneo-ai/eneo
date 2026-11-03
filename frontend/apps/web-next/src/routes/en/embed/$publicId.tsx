import { createFileRoute } from "@tanstack/react-router";
import { EmbedRoute, EmbedError } from "@/features/widget/embed-route";
import { loadEmbedConfig } from "@/features/widget/embed-config";
import { PREVIEW_QUERY } from "@/features/widget/preview";
import { embedSearch } from "@/features/widget/urls";

export const Route = createFileRoute("/en/embed/$publicId")({
  validateSearch: embedSearch,
  loaderDeps: ({ search }) => ({ preview: search[PREVIEW_QUERY] === "1" }),
  loader: ({ params, deps, abortController }) =>
    deps.preview ? null : loadEmbedConfig(params.publicId, abortController.signal),
  head: ({ loaderData, match }) => ({
    meta: [
      {
        title:
          loaderData?.texts.title || loaderData?.name || match.context.t("widget_preview_title")
      },
      { name: "robots", content: "noindex, nofollow" }
    ]
  }),
  remountDeps: ({ params }) => params.publicId,
  errorComponent: EmbedError,
  component: Page
});
function Page() {
  return <EmbedRoute publicId={Route.useParams().publicId} config={Route.useLoaderData()} />;
}
