import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getLatestSyncJob,
  getSyncJob,
  startComponentSyncJob,
  startEvidenceSyncJob,
} from "./api";
import type { SyncJob, SyncJobKind } from "./api";
import { parseApiTimestamp } from "./i18n";
import { readSyncModePreference } from "./syncPreferences";

const POLL_INTERVAL_MS = 1_000;
const POLL_RETRY_MS = 3_000;
// Terminal cards stay visible until dismissed. A slow, read-only lookup lets
// them notice the backend's delayed automatic retry (or a retry started in a
// different tab) without turning the idle app into a hot poller.
const TERMINAL_DISCOVERY_MS = 5_000;
// Rolling readout: how often a *running* job may invite its consumers to
// re-read the mirror. An evidence sweep commits each component as it arrives,
// so the data is already there — without this the screen sat on stale rows for
// the whole run and everything appeared at once at the end. Deliberately much
// slower than the status poll: the status record is tiny, a mirror re-read is
// not, and a person only needs to see the sweep filling in, not every row the
// instant it lands.
const PROGRESSIVE_REFRESH_MS = 8_000;
// A component job is committed just before its evidence follow-up is leased.
// These bounded retries bridge that short race without turning idle screens
// into a permanent discovery poller.
const FOLLOW_UP_DISCOVERY_DELAYS_MS = [0, 750, 2_000] as const;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function isSyncJobActive(job: SyncJob | null): boolean {
  return job?.status === "queued" || job?.status === "running";
}

export function syncJobElapsedSeconds(job: SyncJob, nowMs = Date.now()): number {
  const start = parseApiTimestamp(job.started_at ?? job.created_at).getTime();
  const finish =
    job.finished_at === null ? nowMs : parseApiTimestamp(job.finished_at).getTime();
  if (Number.isNaN(start) || Number.isNaN(finish)) return 0;
  return Math.max(0, Math.floor((finish - start) / 1_000));
}

// Compatibility exports for the original component-only progress surface.
export const isComponentSyncActive = isSyncJobActive;
export const componentSyncElapsedSeconds = syncJobElapsedSeconds;

export type SyncJobController = {
  kind: SyncJobKind;
  job: SyncJob | null;
  active: boolean;
  discovering: boolean;
  starting: boolean;
  startError: string | null;
  pollError: string | null;
  /**
   * Increments while a job is running and has actually advanced, at most every
   * `PROGRESSIVE_REFRESH_MS`. It stops at the terminal status on purpose:
   * consumers already reload on `succeeded`, and bumping again there would
   * only buy a duplicate fetch.
   *
   * Consumers that read the mirror can depend on this to fill in progressively
   * instead of waiting for the terminal status. Only meaningful for jobs that
   * commit incrementally — the evidence sweep commits per component, while the
   * component sync writes its whole mirror in one final transaction and has
   * nothing to show mid-run.
   */
  dataEpoch: number;
  start: (instituteCode: string) => Promise<void>;
  dismiss: () => void;
};

export type ComponentSyncController = SyncJobController;
export type EvidenceSyncController = SyncJobController;

type StartSyncJob = (instituteCode: string) => Promise<SyncJob>;

function usePersistedSyncJob(
  kind: SyncJobKind,
  startJob: StartSyncJob,
  enabled: boolean,
  followUpAfterId: number | null = null,
  followUpInstituteCode: string | null = null,
): SyncJobController {
  const [job, setJob] = useState<SyncJob | null>(null);
  const [discovering, setDiscovering] = useState(enabled);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [dataEpoch, setDataEpoch] = useState(0);
  // Throttle state for the rolling readout. Refs, not state: updating these
  // must never itself schedule a render, or the poll loop would re-run.
  const lastRefresh = useRef({ at: 0, current: -1, jobId: -1 });
  const startInFlight = useRef<Promise<void> | null>(null);

  useEffect(() => {
    if (!enabled) {
      setDiscovering(false);
      return;
    }

    const ctrl = new AbortController();
    let timer: number | null = null;
    const delays =
      followUpAfterId === null ? ([0] as const) : FOLLOW_UP_DISCOVERY_DELAYS_MS;
    setDiscovering(true);

    const finish = () => {
      if (!ctrl.signal.aborted) setDiscovering(false);
    };

    const discover = async (attempt: number) => {
      try {
        const latestJob = await getLatestSyncJob(
          kind,
          followUpInstituteCode ?? undefined,
          ctrl.signal,
        );
        if (ctrl.signal.aborted) return;
        const isNewFollowUp =
          followUpAfterId === null ||
          (latestJob !== null && latestJob.id > followUpAfterId);
        if (latestJob !== null && latestJob.kind === kind && isNewFollowUp) {
          // Preserve a job started while discovery was in flight. Otherwise a
          // newly discovered follow-up supersedes the previous terminal row.
          setJob((current) => (isSyncJobActive(current) ? current : latestJob));
          finish();
          return;
        }
        if (attempt + 1 < delays.length) {
          timer = window.setTimeout(
            () => void discover(attempt + 1),
            delays[attempt + 1],
          );
          return;
        }
      } catch (error) {
        if (ctrl.signal.aborted || isAbortError(error)) return;
        // Discovery is best-effort. Explicit starts and progress polling own
        // their actionable error messages.
      }
      finish();
    };

    void discover(0);
    return () => {
      ctrl.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [enabled, followUpAfterId, followUpInstituteCode, kind]);

  const jobId = job?.id ?? null;
  const jobStatus = job?.status ?? null;
  useEffect(() => {
    if (!enabled || jobId === null || (jobStatus !== "queued" && jobStatus !== "running")) {
      return;
    }

    const ctrl = new AbortController();
    let timer: number | null = null;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void poll(), delay);
    };

    /**
     * Invite consumers to re-read the mirror, but only when it can pay off:
     * the job must have moved (`current` advanced) since the last invitation,
     * and at most one invitation per `PROGRESSIVE_REFRESH_MS`. A job that is
     * retrying a slow page keeps its heartbeat fresh without advancing, and
     * re-reading the mirror for that would cost a request and show nothing.
     */
    const maybeAdvanceEpoch = (next: SyncJob) => {
      const previous = lastRefresh.current;
      const now = Date.now();
      if (previous.jobId !== next.id) {
        // A different job: arm the throttle without firing, so switching jobs
        // does not by itself trigger a refetch.
        lastRefresh.current = { at: now, current: next.current, jobId: next.id };
        return;
      }
      if (next.current <= previous.current) return;
      if (now - previous.at < PROGRESSIVE_REFRESH_MS) return;
      lastRefresh.current = { at: now, current: next.current, jobId: next.id };
      setDataEpoch((epoch) => epoch + 1);
    };

    const poll = async () => {
      try {
        const next = await getSyncJob(jobId, ctrl.signal);
        if (ctrl.signal.aborted) return;
        if (next.kind !== kind) {
          throw new Error(`Sync job ${jobId} changed kind unexpectedly.`);
        }
        setJob(next);
        setPollError(null);
        if (isSyncJobActive(next)) {
          maybeAdvanceEpoch(next);
          schedule(POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (ctrl.signal.aborted || isAbortError(error)) return;
        setPollError(errorMessage(error));
        // A progress-channel failure does not mean the server-side sync failed.
        schedule(POLL_RETRY_MS);
      }
    };

    schedule(350);
    return () => {
      ctrl.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [enabled, jobId, jobStatus, kind]);

  const jobInstituteCode = job?.institute_code ?? null;
  useEffect(() => {
    if (
      !enabled ||
      jobId === null ||
      jobInstituteCode === null ||
      jobStatus === "queued" ||
      jobStatus === "running"
    ) {
      return;
    }

    const ctrl = new AbortController();
    let timer: number | null = null;

    const discoverNewer = async () => {
      try {
        const latest = await getLatestSyncJob(kind, jobInstituteCode, ctrl.signal);
        if (ctrl.signal.aborted) return;
        if (
          latest !== null &&
          latest.kind === kind &&
          latest.institute_code === jobInstituteCode &&
          latest.id > jobId
        ) {
          setJob((current) =>
            current !== null &&
            current.id === jobId &&
            current.kind === kind &&
            current.institute_code === jobInstituteCode
              ? latest
              : current,
          );
          return;
        }
      } catch (error) {
        if (ctrl.signal.aborted || isAbortError(error)) return;
        // Best-effort discovery must not replace the actionable terminal
        // result with a second, connectivity-shaped error.
      }
      if (!ctrl.signal.aborted) {
        timer = window.setTimeout(() => void discoverNewer(), TERMINAL_DISCOVERY_MS);
      }
    };

    timer = window.setTimeout(() => void discoverNewer(), TERMINAL_DISCOVERY_MS);
    return () => {
      ctrl.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [enabled, jobId, jobInstituteCode, jobStatus, kind]);

  const start = useCallback(
    (instituteCode: string) => {
      if (startInFlight.current !== null) return startInFlight.current;

      setStarting(true);
      setStartError(null);
      setPollError(null);
      const request = (async () => {
        try {
          // The server returns the existing global job if another tab/operator
          // already started one, so every caller converges on the same job id.
          const next = await startJob(instituteCode);
          if (next.kind !== kind) {
            throw new Error(`The server returned an unexpected ${next.kind} sync job.`);
          }
          setJob(next);
        } catch (error) {
          setStartError(errorMessage(error));
        } finally {
          startInFlight.current = null;
          setStarting(false);
        }
      })();
      startInFlight.current = request;
      return request;
    },
    [kind, startJob],
  );

  const dismiss = useCallback(() => {
    setJob((current) => (isSyncJobActive(current) ? current : null));
    setStartError(null);
    setPollError(null);
  }, []);

  const active = isSyncJobActive(job);
  return useMemo(
    () => ({
      kind,
      job,
      active,
      discovering,
      starting,
      startError,
      pollError,
      dataEpoch,
      start,
      dismiss,
    }),
    [
      kind,
      job,
      active,
      discovering,
      starting,
      startError,
      pollError,
      dataEpoch,
      start,
      dismiss,
    ],
  );
}

/**
 * App-shell-owned component-sync state. The backend persists the job; the hook
 * discovers a live run after reload and polls only its small status record.
 */
export function useComponentSyncJob(enabled = true): ComponentSyncController {
  return usePersistedSyncJob("components", startComponentSyncJob, enabled);
}

/**
 * App-shell-owned evidence-sync state. Manual component and evidence jobs are
 * independent; each evidence start and retry uses the current browser scope.
 */
export function useEvidenceSyncJob(enabled = true): EvidenceSyncController {
  const startWithPreference = useCallback(
    (instituteCode: string) =>
      startEvidenceSyncJob(instituteCode, readSyncModePreference()),
    [],
  );
  return usePersistedSyncJob("evidence", startWithPreference, enabled);
}
