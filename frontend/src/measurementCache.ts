/**
 * Small stale-while-revalidate cache for the Statistics measurement views.
 *
 * The payload is local mirror data only; no credential or session value is
 * persisted. Entries are isolated by the signed-in local account/institute
 * scope supplied by AppShell and by an opaque evidence-mirror revision hint.
 * A matching revision is returned without another expensive aggregation.
 * When the revision changes, the previous value paints immediately while one
 * shared background request refreshes it.
 */

import {
  getMeasurementDimensions,
  getMeasurementSeries,
  type MeasurementDimensions,
  type MeasurementSeries,
} from "./api";

export type MeasurementSeriesQuery = {
  test_type: string;
  result: string;
  x_result?: string;
};

export type CachedLoad<T> = {
  cached: T | null;
  refresh: Promise<T> | null;
};

type CacheEntry<T> = {
  revision: string;
  value: T;
  touchedAt: number;
};

type StoredCache = {
  version: 1;
  dimensions: CacheEntry<MeasurementDimensions> | null;
  series: Record<string, CacheEntry<MeasurementSeries>>;
};

const STORAGE_PREFIX = "itkflow.measurements.cache.v1";
const MAX_PERSISTED_BYTES = 4_000_000;
const memory = new Map<string, StoredCache>();
type RefreshState = {
  requestedRevision: string;
  promise: Promise<unknown>;
};
const inFlight = new Map<string, RefreshState>();

function storageKey(scope: string): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(scope)}`;
}

function emptyCache(): StoredCache {
  return { version: 1, dimensions: null, series: {} };
}

function readStored(scope: string): StoredCache {
  const existing = memory.get(scope);
  if (existing !== undefined) return existing;
  let parsed = emptyCache();
  try {
    const raw = window.localStorage.getItem(storageKey(scope));
    if (raw !== null) {
      const candidate = JSON.parse(raw) as Partial<StoredCache>;
      if (candidate.version === 1 && typeof candidate.series === "object") {
        parsed = {
          version: 1,
          dimensions: candidate.dimensions ?? null,
          series: candidate.series ?? {},
        };
      }
    }
  } catch {
    // Blocked/corrupt storage only disables persistence; the memory cache is
    // still useful for navigation inside this app process.
  }
  memory.set(scope, parsed);
  return parsed;
}

function persist(scope: string, cache: StoredCache): void {
  memory.set(scope, cache);
  try {
    let serialized = JSON.stringify(cache);
    if (serialized.length > MAX_PERSISTED_BYTES) {
      // Keep dimensions and the most recently used series. This is a cache,
      // never the source of truth, so deterministic LRU eviction is safe.
      const ordered = Object.entries(cache.series).sort(
        ([leftKey, left], [rightKey, right]) =>
          right.touchedAt - left.touchedAt || leftKey.localeCompare(rightKey),
      );
      const trimmed = { ...cache, series: {} as StoredCache["series"] };
      // Dimensions alone may already be close to the limit. Start with the
      // trimmed representation so an empty series set never writes the
      // original oversized payload by accident.
      serialized = JSON.stringify(trimmed);
      for (const [key, entry] of ordered) {
        trimmed.series[key] = entry;
        const candidate = JSON.stringify(trimmed);
        if (candidate.length > MAX_PERSISTED_BYTES) {
          delete trimmed.series[key];
          continue;
        }
        serialized = candidate;
      }
      memory.set(scope, trimmed);
    }
    window.localStorage.setItem(storageKey(scope), serialized);
  } catch {
    // Quota/security errors must never break Statistics.
  }
}

export function measurementSeriesKey(query: MeasurementSeriesQuery): string {
  return JSON.stringify([query.test_type, query.result, query.x_result ?? ""]);
}

function sharedRefresh<T>(
  key: string,
  revision: string,
  request: () => Promise<T>,
  store: (value: T, settledRevision: string) => void,
): Promise<T> {
  const pending = inFlight.get(key);
  if (pending !== undefined) {
    // Progressive evidence sync can advance its epoch faster than an
    // aggregation completes. Keep only the newest requested revision and let
    // the active request finish before issuing one trailing refresh.
    pending.requestedRevision = revision;
    return pending.promise as Promise<T>;
  }

  const state: RefreshState = {
    requestedRevision: revision,
    promise: Promise.resolve(undefined),
  };
  const started = (async () => {
    while (true) {
      const requestedRevision = state.requestedRevision;
      let value: T;
      try {
        value = await request();
      } catch (error) {
        // If this request was already superseded, give the newest revision
        // its own attempt instead of surfacing an obsolete failure.
        if (state.requestedRevision !== requestedRevision) continue;
        throw error;
      }
      if (state.requestedRevision !== requestedRevision) continue;
      store(value, requestedRevision);
      return value;
    }
  })().finally(() => {
    if (inFlight.get(key) === state) inFlight.delete(key);
  });
  state.promise = started;
  inFlight.set(key, state);
  return started;
}

export function loadMeasurementDimensions(
  scope: string,
  revision: string,
): CachedLoad<MeasurementDimensions> {
  const cache = readStored(scope);
  const targetKey = JSON.stringify([scope, "dimensions"]);
  const cached = cache.dimensions?.value ?? null;
  if (cache.dimensions?.revision === revision) return { cached, refresh: null };
  const refresh = sharedRefresh(
    targetKey,
    revision,
    () => getMeasurementDimensions(),
    (value, settledRevision) => {
      const current = readStored(scope);
      persist(scope, {
        ...current,
        dimensions: { revision: settledRevision, value, touchedAt: Date.now() },
      });
    },
  );
  return { cached, refresh };
}

export function loadMeasurementSeries(
  scope: string,
  revision: string,
  query: MeasurementSeriesQuery,
): CachedLoad<MeasurementSeries> {
  const cache = readStored(scope);
  const seriesKey = measurementSeriesKey(query);
  const targetKey = JSON.stringify([scope, "series", seriesKey]);
  const entry = cache.series[seriesKey];
  const cached = entry?.value ?? null;
  if (entry?.revision === revision) return { cached, refresh: null };
  const refresh = sharedRefresh(
    targetKey,
    revision,
    () => getMeasurementSeries(query),
    (value, settledRevision) => {
      const current = readStored(scope);
      persist(scope, {
        ...current,
        series: {
          ...current.series,
          [seriesKey]: { revision: settledRevision, value, touchedAt: Date.now() },
        },
      });
    },
  );
  return { cached, refresh };
}

/** Test/logout utility and an explicit escape hatch for future authoritative
 * mirror revision events that need to discard every cached payload. */
export function clearMeasurementCache(scope?: string): void {
  if (scope !== undefined) {
    memory.delete(scope);
    try {
      window.localStorage.removeItem(storageKey(scope));
    } catch {
      // Best effort.
    }
  } else {
    memory.clear();
    try {
      for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
        const key = window.localStorage.key(index);
        if (key?.startsWith(`${STORAGE_PREFIX}:`)) window.localStorage.removeItem(key);
      }
    } catch {
      // Best effort.
    }
  }
  inFlight.clear();
}
