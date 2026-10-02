"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { EneoApiError, getErrorMessage } from "@/lib/api/errors";
import { LoadingState, type LoadingStateProps } from "./loading-state";

/** The part of a React Query result the boundary reads; any `useQuery` result fits. */
export type QueryLike<T = unknown> = {
  data: T | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isFetching: boolean;
  refetch: () => unknown;
};

export type ListErrorProps = {
  /** The failure; its message comes from the error catalog (`getErrorMessage`). */
  error: unknown;
  /** Runs the request again (a query's `refetch`). */
  onRetry: () => void;
  /** The retry is in flight: the button shows a spinner and a second press is ignored. */
  isRetrying?: boolean;
  /** Replaces the generic title ("The content could not be loaded"). */
  title?: string;
  className?: string;
};

/**
 * The one error state for a list or section that failed to load: an Astryx
 * error banner (announced as an alert) with the catalog's message, a
 * "Försök igen" button and, for a backend error, the HTTP status, error code
 * and trace id behind the banner's details toggle.
 *
 * @example
 * {query.isError ? <ListError error={query.error} onRetry={() => void query.refetch()} /> : …}
 */
export function ListError({
  error,
  onRetry,
  isRetrying = false,
  title,
  className
}: ListErrorProps) {
  const t = useTranslations();
  const apiError = error instanceof EneoApiError ? error : null;
  const details = apiError
    ? [
        t("query_error_http_status", { status: apiError.status }),
        apiError.code != null ? t("query_error_code", { code: apiError.code }) : null,
        apiError.traceId ? t("query_error_trace_id", { id: apiError.traceId }) : null
      ].filter((line): line is string => line !== null)
    : [];

  return (
    <Banner
      status="error"
      title={title ?? t("query_error_title")}
      description={getErrorMessage(error, t)}
      className={className}
      endContent={
        <Button
          size="sm"
          label={t("retry")}
          icon={<RefreshCw aria-hidden="true" />}
          isLoading={isRetrying}
          isInterruptible
          onClick={() => {
            if (!isRetrying) onRetry();
          }}
        />
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
 * Renders a query's three states the same way everywhere: `LoadingState`
 * skeleton rows while pending, `ListError` with a retry when it failed
 * (retrying the failed queries only) and the children once there is data.
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
  const { rows, variant, height, loadingLabel } = props;
  const queries: readonly QueryLike[] = props.queries ?? [props.query];
  const failed = queries.filter((query) => query.isError);

  if (failed.length > 0) {
    return (
      <ListError
        error={failed[0]!.error}
        isRetrying={failed.some((query) => query.isFetching)}
        onRetry={() => {
          for (const query of failed) void query.refetch();
        }}
      />
    );
  }
  if (queries.some((query) => query.isPending)) {
    return <LoadingState rows={rows} variant={variant} height={height} label={loadingLabel} />;
  }
  if (props.queries) return <>{props.children()}</>;
  return <>{props.children(props.query.data as T)}</>;
}
