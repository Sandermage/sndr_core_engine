// SPDX-License-Identifier: Apache-2.0
// Tiny in-memory stale-while-revalidate cache. Many panels (Containers,
// Virtualization) re-fetch slow SSH/registry round-trips every time the section
// is opened, which makes navigating back feel sluggish. This module keeps the
// last value per key so a re-open paints instantly from cache while the caller
// revalidates in the background.
//
// Pattern:
//   const stale = cachePeek<T>(key);        // show immediately (any age)
//   if (stale) setState(stale);
//   if (!cacheGet<T>(key, TTL)) {            // only hit the network if not fresh
//     fetchIt().then((v) => { cacheSet(key, v); setState(v); });
//   }
//
// It is intentionally process-local and unbounded-by-time but bounded in size by
// the number of distinct keys (hosts × resources), which is small.

interface Entry {
  value: unknown;
  at: number;
}

const store = new Map<string, Entry>();

// Fresh value only — returns undefined once older than ttlMs, signalling the
// caller to revalidate.
export function cacheGet<T>(key: string, ttlMs: number): T | undefined {
  const entry = store.get(key);
  if (entry && Date.now() - entry.at < ttlMs) return entry.value as T;
  return undefined;
}

// Last value regardless of age — for the instant stale paint.
export function cachePeek<T>(key: string): T | undefined {
  return store.get(key)?.value as T | undefined;
}

export function cacheSet<T>(key: string, value: T): void {
  store.set(key, { value, at: Date.now() });
}

// Drop everything, or just the keys under a prefix (e.g. one host's data).
export function cacheClear(prefix?: string): void {
  if (!prefix) {
    store.clear();
    return;
  }
  for (const key of Array.from(store.keys())) {
    if (key.startsWith(prefix)) store.delete(key);
  }
}
