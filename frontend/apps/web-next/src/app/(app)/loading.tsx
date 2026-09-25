import { LoadingState } from "@/components/composites/loading-state";

/** Route-level loading inside the page panel: a busy status region, announced once. */
export default function AppLoading() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col p-4 sm:p-6">
      <LoadingState rows={4} />
    </div>
  );
}
