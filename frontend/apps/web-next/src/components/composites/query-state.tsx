"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { EneoApiError, errorReferenceLines, getErrorMessage } from "@/lib/api/errors";
import { LoadingState, type LoadingStateProps } from "./loading-state";

/** The part of a React Query result the boundary reads; any `useQuery` result fits. */
export type QueryLike<T = unknown> = {
  data: T | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isFetching: boolean;
  errorUpdatedAt: number;
  dataUpdatedAt: number;
  /** An infinite query's next page failed: `LoadMore` reports that, not the boundary. */
  isFetchNextPageError?: boolean;
  refetch: () => unknown;
};

/**
 * A failure that leaves nothing to show: the query failed without data, or
 * it is retrying such a failure. React Query reports that retry as pending
 * (fetching, or paused while offline) and clears isError, so this reads
 * `errorUpdatedAt > dataUpdatedAt` to keep the retry button under the user's
 * focus instead of swapping in a skeleton. A failure with data on screen is
 * not blocking: the data stays.
 */
export function blockingError(
  query: Pick<QueryLike, "data" | "isError" | "isPending" | "errorUpdatedAt" | "dataUpdatedAt">
): boolean {
  if (query.data !== undefined) return false;
  return query.isError || (query.isPending && query.errorUpdatedAt > query.dataUpdatedAt);
}

export type ListErrorProps = {
  /**
   * The failure; its message comes from the error catalog (`getErrorMessage`).
   * Without one (null or undefined) only the title shows.
   */
  error: unknown;
  /** Runs the request again (a query's `refetch`); without it there is no retry button. */
  onRetry?: () => void;
  /** The retry is in flight: the button shows a spinner and a second press is ignored. */
  isRetrying?: boolean;
  /** Replaces the generic title ("The content could not be loaded"); site-specific copy goes here. */
  title?: string;
  /**
   * One line for a failure beside content that stays on screen: the catalog's
   * message is the title (no generic heading) unless `title` is given.
   */
  compact?: boolean;
  className?: string;
};

/**
 * The one inline error display: an Astryx error banner (announced as an
 * alert) with the catalog's message, an optional "Försök igen" button and,
 * for a backend error, the HTTP status, error code and the support references
 * (`errorReferenceLines`: error id and trace id) behind the banner's details
 * toggle. Keep errors as `unknown` in state and render them here.
 *
 * A failed read goes through `QueryStateBoundary`, or `blockingError` plus
 * `RefreshError` where content cannot sit in a boundary: a plain `isError`
 * check drops the retry button under focus and hides data on a failed
 * refetch. Use ListError directly for a failed save or other mutation.
 *
 * @example
 * {saveError != null && <ListError error={saveError} title={t("skills_bindings_save_error")} />}
 *
 * @example
 * {blockingError(query) ? (
 *   <ListError error={query.error} isRetrying={query.isFetching} onRetry={() => void query.refetch()} />
 * ) : …}
 */
export function ListError({
  error,
  onRetry,
  isRetrying = false,
  title,
  compact = false,
  className
}: ListErrorProps) {
  const t = useTranslations();
  const apiError = error instanceof EneoApiError ? error : null;
  const details = apiError
    ? [
        t("query_error_http_status", { status: apiError.status }),
        apiError.code != null ? t("query_error_code", { code: apiError.code }) : null,
        ...errorReferenceLines(apiError, t)
      ].filter((line): line is string => line !== null)
    : [];
  const message = getErrorMessage(error, t);
  const heading = title ?? (compact ? message : t("query_error_title"));

  return (
    <Banner
      status="error"
      title={heading}
      description={error == null || heading === message ? undefined : message}
      className={className}
      endContent={
        onRetry ? (
          <Button
            size="sm"
            label={t("retry")}
            // Several failed sections on one page: each retry names its own.
            aria-label={title ? t("query_error_retry_named", { section: title }) : undefined}
            icon={<RefreshCw aria-hidden="true" />}
            isLoading={isRetrying}
            isInterruptible
            onClick={() => {
              if (!isRetrying) onRetry();
            }}
          />
        ) : undefined
      }
    >
      {details.length > 0 ? (
        <ul className="text-ax-text-secondary flex flex-col gap-1 font-mono text-xs">
          {details.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : undefined}
    </Banner>
  );
}

type LoadingProps = Pick<LoadingStateProps, "rows" | "variant" | "height"> & {
  /** Screen-reader label while loading; defaults to "Laddar…". */
  loadingLabel?: string;
  /** Title of the error that replaces the content (ListError's `title`). */
  errorTitle?: string;
};

type SingleQueryProps<T> = LoadingProps & {
  /** The query the content depends on. */
  query: QueryLike<T>;
  /** The content, once the query has data. */
  children: (data: T) => ReactNode;
  queries?: never;
};

type ManyQueriesProps = LoadingProps & {
  /** Several queries the content depends on: loading until all have data, an error if any failed. */
  queries: readonly QueryLike[];
  /** The content, once every query has data (read it from the queries). */
  children: () => ReactNode;
  query?: never;
};

export type QueryStateBoundaryProps<T> = SingleQueryProps<T> | ManyQueriesProps;

/**
 * Renders a query's states the same way everywhere: `LoadingState` skeleton
 * rows while pending, `ListError` with a retry when a failure leaves nothing
 * to show (`blockingError`; retrying the failed queries only) and the children
 * once there is data. A refetch that fails while data is shown keeps the
 * children and puts a compact `ListError` above them.
 *
 * @example
 * <QueryStateBoundary query={logs} rows={5}>
 *   {(data) => <AuditTable logs={data.logs} />}
 * </QueryStateBoundary>
 *
 * @example
 * <QueryStateBoundary queries={[roles, permissions]} rows={4}>
 *   {() => <RoleList roles={roles.data ?? []} />}
 * </QueryStateBoundary>
 */
export function QueryStateBoundary<T>(props: QueryStateBoundaryProps<T>) {
  const { rows, variant, height, loadingLabel, errorTitle } = props;
  const queries: readonly QueryLike[] = props.queries ?? [props.query];
  const blocking = queries.filter(blockingError);
  if (blocking.length > 0) {
    return (
      <ListError
        error={blocking.find((query) => query.error != null)?.error ?? null}
        title={errorTitle}
        isRetrying={blocking.some((query) => query.isFetching)}
        onRetry={() => {
          for (const query of blocking) void query.refetch();
        }}
      />
    );
  }
  if (queries.some((query) => query.isPending)) {
    return <LoadingState rows={rows} variant={variant} height={height} label={loadingLabel} />;
  }
  return (
    <>
      <RefreshError queries={queries} />
      {props.queries ? props.children() : props.children(props.query.data as T)}
    </>
  );
}

type FailureKind = "refresh" | "next-page" | null;

/** Which failure a query with data on screen holds: its refresh or its next page. */
function failureKind(query: Pick<QueryLike, "data" | "isError" | "isFetchNextPageError">) {
  if (!query.isError || query.data === undefined) return null;
  return query.isFetchNextPageError ? "next-page" : "refresh";
}

/**
 * The failure each query last settled with. While a fetch runs, React Query
 * describes that fetch (its direction), not the failure on screen: a failed
 * refresh would read as a failed next page once "Visa fler" is pressed, and a
 * failed next page as a failed refresh once a focus refetch starts. The kind
 * is kept until the fetch ends.
 */
function useSettledFailures(
  queries: readonly Pick<QueryLike, "data" | "isError" | "isFetching" | "isFetchNextPageError">[]
): FailureKind[] {
  const [settled, setSettled] = useState<FailureKind[]>(() => queries.map(failureKind));
  const kinds = queries.map((query, index) =>
    query.isFetching ? (settled[index] ?? null) : failureKind(query)
  );
  if (kinds.length !== settled.length || kinds.some((kind, index) => kind !== settled[index])) {
    setSettled(kinds);
  }
  return kinds;
}

/**
 * The compact error above content that stays on screen when a refetch of it
 * failed (focus, invalidation, polling): "could not be refreshed, the last
 * loaded data is shown" with a retry of the failed queries. Renders nothing
 * otherwise; a failure with nothing to show is `blockingError`'s, and a failed
 * next page is `LoadMore`'s. `QueryStateBoundary` renders it; use it directly
 * where content cannot sit in a boundary.
 */
export function RefreshError({ queries }: { queries: readonly QueryLike[] }) {
  const t = useTranslations();
  const kinds = useSettledFailures(queries);
  const failed = queries.filter((_, index) => kinds[index] === "refresh");
  if (failed.length === 0) return null;
  return (
    <ListError
      error={failed[0]!.error}
      title={t("query_error_refresh_title")}
      isRetrying={failed.some((query) => query.isFetching)}
      onRetry={() => {
        for (const query of failed) void query.refetch();
      }}
      compact
    />
  );
}

/** The part of a `useInfiniteQuery` result `LoadMore` reads. */
export type InfiniteQueryLike = {
  data: unknown;
  isError: boolean;
  isFetching: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isFetchNextPageError: boolean;
  error: unknown;
  fetchNextPage: () => unknown;
};

/**
 * The "load more" control under a paged list. While the next page loads the
 * button stays enabled (it keeps focus) and a second press is ignored. A
 * failed next page keeps the loaded rows: a compact `ListError` above the
 * button retries that page only.
 *
 * @example
 * <LoadMore query={sessions} label={t("load_more_conversations")} />
 */
export function LoadMore({
  query,
  label,
  onLoad
}: {
  query: InfiniteQueryLike;
  label: string;
  /** Replaces `fetchNextPage`, e.g. to move focus to the first new row once it renders. */
  onLoad?: () => void;
}) {
  const t = useTranslations();
  const [failure] = useSettledFailures([query]);
  const failed = failure === "next-page";
  if (!query.hasNextPage && !failed) return null;
  const load = () => {
    if (query.isFetchingNextPage) return;
    if (onLoad) onLoad();
    else void query.fetchNextPage();
  };

  return (
    <div className="flex flex-col items-center gap-2">
      {failed ? (
        <ListError
          error={query.error}
          title={t("query_error_load_more_title")}
          isRetrying={query.isFetchingNextPage}
          onRetry={load}
          compact
          className="w-full"
        />
      ) : null}
      {query.hasNextPage ? (
        <Button label={label} isLoading={query.isFetchingNextPage} isInterruptible onClick={load} />
      ) : null}
    </div>
  );
}
