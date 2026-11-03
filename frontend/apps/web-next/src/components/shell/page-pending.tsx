import { LoadingState } from "@/components/composites/loading-state";
import { PageFrame } from "@/components/composites/page-frame";

/** Route-level loading inside the page panel: a busy status region, announced once. */
export function PagePending() {
  return (
    <PageFrame>
      <LoadingState rows={4} />
    </PageFrame>
  );
}
