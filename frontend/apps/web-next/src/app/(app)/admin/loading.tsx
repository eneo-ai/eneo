import { LoadingState } from "@/components/composites/loading-state";

/**
 * Route-level loading for admin pages, inside their padding (admin/layout.tsx:
 * a phone's 16 px gutter up to 768 px), so a page does not shift when it
 * replaces this.
 */
export default function AdminLoading() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col">
      <LoadingState rows={4} />
    </div>
  );
}
