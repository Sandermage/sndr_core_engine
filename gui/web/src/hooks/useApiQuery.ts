// SPDX-License-Identifier: Apache-2.0
import { useQuery } from "@tanstack/react-query";

/** Fetch-state machine shared by the read hooks. */
export type FetchState = "idle" | "loading" | "ready" | "error";

/**
 * `useFetch`-compatible read hook, backed by TanStack Query: a shared, deduped
 * cache (navigating back to a panel doesn't re-hit the daemon), built-in retry,
 * and AbortSignal cancellation. Unlike `useFetch`, the caller passes an EXPLICIT
 * `queryKey` so two different fetchers can never collide on the same cache slot
 * (the hazard that blocks backing `useFetch` transparently). The returned shape
 * matches `useFetch` (`{ data, state, error, reload }`) so call sites migrate by
 * swapping the hook + adding a key — no consumer changes.
 */
export function useApiQuery<T>(
  queryKey: readonly unknown[],
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: { enabled?: boolean; staleTime?: number } = {},
): { data: T | null; state: FetchState; error: string | null; reload: () => void } {
  const enabled = opts.enabled ?? true;
  const q = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetcher(signal),
    enabled,
    ...(opts.staleTime !== undefined ? { staleTime: opts.staleTime } : {}),
  });
  const state: FetchState = !enabled
    ? "idle"
    : q.status === "error"
      ? "error"
      : q.status === "success"
        ? "ready"
        : q.fetchStatus === "fetching"
          ? "loading"
          : "idle";
  return {
    data: q.data ?? null,
    state,
    error: q.error ? (q.error instanceof Error ? q.error.message : String(q.error)) : null,
    reload: () => { void q.refetch(); },
  };
}
