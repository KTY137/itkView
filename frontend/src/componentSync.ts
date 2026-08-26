import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getLatestSyncJob,
  getSyncJob,
  startComponentSyncJob,
  startEvidenceSyncJob,
} from "./api";
import type { SyncJob, SyncJobKind } from "./api";
import { parseApiTimestamp } from "./i18n";

const POLL_INTERVAL_MS = 1_000;
const POLL_RETRY_MS = 3_000;
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
  startError: string | null;
  pollError: string | null;
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
  const [startError, setStartError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

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

    const poll = async () => {
      try {
        const next = await getSyncJob(jobId, ctrl.signal);
        if (ctrl.signal.aborted) return;
        if (next.kind !== kind) {
          throw new Error(`Sync job ${jobId} changed kind unexpectedly.`);
        }
        setJob(next);
        setPollError(null);
        if (isSyncJobActive(next)) schedule(POLL_INTERVAL_MS);
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

  const start = useCallback(
    async (instituteCode: string) => {
      setStartError(null);
      setPollError(null);
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
      }
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
    () => ({ kind, job, active, discovering, startError, pollError, start, dismiss }),
    [kind, job, active, discovering, startError, pollError, start, dismiss],
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
 * App-shell-owned evidence-sync state. A successful component job triggers a
 * bounded rediscovery so its automatically queued evidence follow-up becomes
 * visible despite the small commit/enqueue race.
 */
export function useEvidenceSyncJob(
  enabled = true,
  componentJob: SyncJob | null = null,
): EvidenceSyncController {
  const followUpDiscoveryKey =
    componentJob?.kind === "components" && componentJob.status === "succeeded"
      ? componentJob.id
      : null;
  const followUpInstituteCode =
    componentJob?.kind === "components" && componentJob.status === "succeeded"
      ? componentJob.institute_code
      : null;
  return usePersistedSyncJob(
    "evidence",
    startEvidenceSyncJob,
    enabled,
    followUpDiscoveryKey,
    followUpInstituteCode,
  );
}
