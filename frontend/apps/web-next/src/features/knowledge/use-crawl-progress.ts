"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import {
  ACTIVE_CRAWL_REFRESH_MS,
  IDLE_CRAWL_REFRESH_MS,
  endedCrawls,
  withCrawlProgress,
  type CrawlProgress
} from "./crawl-progress";
import { websiteCrawlProgressQueryOptions, type Website } from "./knowledge";
import { isActiveCrawl } from "./website-status";

const NO_RUNS: CrawlProgress = new Map();

/**
 * The websites of a space with their running crawls kept current. While a
 * crawl shows as running, its progress is read every two seconds from the
 * space's crawl progress, a read of the running runs alone, instead of the
 * whole space. Each website shows the newest run either read knows of, so a
 * crawl that ended keeps its last progress until the space says how it ended:
 * the space is refreshed once when a progress read made after the space's
 * own read no longer has a crawl that shows as running. The space keeps its
 * slow poll, which finds crawls a schedule or another user starts and changes
 * to the websites. `pollSpaceFast` is true while crawls run and their
 * progress cannot be read: the caller then polls the space quickly, as before
 * this read existed.
 */
export function useCrawlProgress(websites: readonly Website[]): {
  websites: Website[];
  pollSpaceFast: boolean;
} {
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();

  // The last run each progress read has shown, by website.
  const [polled, setPolled] = useState({
    read: undefined as CrawlProgress | undefined,
    runs: NO_RUNS
  });
  const merged = useMemo(() => withCrawlProgress(websites, polled.runs), [websites, polled.runs]);
  const crawling = merged.some((website) => isActiveCrawl(website.latest_crawl));
  const query = useQuery({
    ...websiteCrawlProgressQueryOptions(browserApi, space.id),
    enabled: crawling,
    refetchInterval: (current) =>
      current.state.status === "error" ? IDLE_CRAWL_REFRESH_MS : ACTIVE_CRAWL_REFRESH_MS
  });
  const progress = query.data;
  if (progress && progress !== polled.read) {
    setPolled({ read: progress, runs: new Map([...polled.runs, ...progress]) });
  }

  // A crawl that shows as running ended if a progress read made after the
  // space's read no longer has it; the space is refreshed once per space read
  // for it, so a read that crossed the refresh asks again.
  const readAt = query.dataUpdatedAt;
  const reconciled = useRef("");
  useEffect(() => {
    if (!progress) return;
    const spaceKey = ["spaces", routeId];
    const spaceReadAt = queryClient.getQueryState(spaceKey)?.dataUpdatedAt ?? 0;
    if (readAt <= spaceReadAt) return;
    const ended = endedCrawls([...websites, ...merged], progress);
    const key = `${spaceReadAt} ${ended}`;
    if (ended === "" || key === reconciled.current) return;
    reconciled.current = key;
    void queryClient.invalidateQueries({ queryKey: spaceKey, exact: true });
  }, [progress, readAt, websites, merged, queryClient, routeId]);

  return { websites: merged, pollSpaceFast: crawling && query.isError };
}
