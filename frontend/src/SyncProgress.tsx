import type { SyncJob, SyncJobPhase } from "./api";
import { isSyncJobActive, syncJobElapsedSeconds } from "./componentSync";
import type { SyncJobController } from "./componentSync";
import { formatAge, formatCount, formatDuration, t } from "./i18n";

const COMPONENT_WORK_PHASES: SyncJobPhase[] = [
  "fetching",
  "mapping",
  "upserting",
  "stage_events",
  "tools",
  "committing",
];

const EVIDENCE_WORK_PHASES: SyncJobPhase[] = [
  "fetching",
  "attachments",
  "committing",
];

function workPhases(job: SyncJob): SyncJobPhase[] {
  return job.kind === "evidence" ? EVIDENCE_WORK_PHASES : COMPONENT_WORK_PHASES;
}

export function syncJobPhaseLabel(job: SyncJob): string {
  if (job.status === "failed") return t.syncJob.failed;
  if (job.status === "interrupted") return t.syncJob.interrupted;
  if (job.status === "succeeded" || job.phase === "complete") {
    return job.kind === "evidence" ? t.syncJob.evidenceComplete : t.syncJob.complete;
  }
  switch (job.phase) {
    case "queued":
      return t.syncJob.queued;
    case "fetching":
      return job.kind === "evidence"
        ? t.syncJob.fetchingEvidence
        : t.syncJob.fetching;
    case "mapping":
      return t.syncJob.mapping;
    case "upserting":
      return t.syncJob.upserting;
    case "stage_events":
      return t.syncJob.stageEvents;
    case "tools":
      return t.syncJob.tools;
    case "attachments":
      return t.syncJob.attachments;
    case "committing":
      return job.kind === "evidence"
        ? t.syncJob.committingEvidence
        : t.syncJob.committing;
  }
}

// Compatibility export for the original component-only caller/tests.
export const componentSyncPhaseLabel = syncJobPhaseLabel;

function jobTone(job: SyncJob): "running" | "success" | "error" {
  if (job.status === "succeeded") return "success";
  if (job.status === "failed" || job.status === "interrupted") return "error";
  return "running";
}

function phaseUnit(job: SyncJob): string {
  if (job.phase === "stage_events") return t.syncJob.eventsUnit;
  if (job.phase === "tools") return t.syncJob.toolsUnit;
  if (job.phase === "attachments") return t.syncJob.filesUnit;
  if (
    job.phase === "fetching" ||
    job.phase === "mapping" ||
    job.phase === "upserting"
  ) {
    return t.syncJob.componentsUnit;
  }
  return t.syncJob.itemsUnit;
}

function phaseStep(job: SyncJob): string | null {
  if (job.phase === "queued") return null;
  const phases = workPhases(job);
  if (job.status === "succeeded") {
    return t.syncJob.step(phases.length, phases.length);
  }
  if (job.phase === "complete") return null;
  const index = phases.indexOf(job.phase);
  return index < 0 ? null : t.syncJob.step(index + 1, phases.length);
}

function countLabel(job: SyncJob): string {
  if (job.total !== null) {
    return t.syncJob.count(
      formatCount(job.current),
      formatCount(job.total),
      phaseUnit(job),
    );
  }
  if (job.current > 0) {
    return t.syncJob.countWithoutTotal(formatCount(job.current), phaseUnit(job));
  }
  return t.syncJob.waitingForTotal;
}

function progressProps(job: SyncJob): {
  value?: number;
  max?: number;
  label: string;
} {
  const phase = syncJobPhaseLabel(job);
  if (job.status === "succeeded") {
    return { value: 1, max: 1, label: t.syncJob.progressLabel(phase, 1, 1) };
  }
  if (job.total !== null && job.total > 0) {
    const current = Math.min(Math.max(job.current, 0), job.total);
    return {
      value: current,
      max: job.total,
      label: t.syncJob.progressLabel(phase, current, job.total),
    };
  }
  if (job.status === "failed" || job.status === "interrupted") {
    return { value: 0, max: 1, label: phase };
  }
  return { label: t.syncJob.indeterminateLabel(phase) };
}

function JobProgress({ job, compact = false }: { job: SyncJob; compact?: boolean }) {
  const progress = progressProps(job);
  return (
    <progress
      className={compact ? "sync-meter compact" : "sync-meter"}
      value={progress.value}
      max={progress.max}
      aria-label={progress.label}
    />
  );
}

function jobTitle(job: SyncJob): string {
  return job.kind === "evidence" ? t.syncJob.evidenceTitle : t.syncJob.title;
}

function resultLabel(job: SyncJob): string | null {
  if (job.result === null) return null;
  if (job.kind === "components") {
    return t.components.syncComplete(
      job.result.created,
      job.result.updated,
      job.result.unchanged,
      job.result.stale,
      job.result.skipped,
    );
  }
  return t.syncJob.evidenceResult(
    job.result.components_processed,
    job.result.created,
    job.result.updated,
    job.result.unchanged,
    job.result.total,
    job.result.attachments_downloaded,
    job.result.attachments_reused,
    job.result.attachments_failed,
    job.result.attachments_total,
  );
}

/** Compact, clickable telemetry shown in the sticky topbar on every screen. */
export function CompactSyncStatus({
  job,
  onOpen,
}: {
  job: SyncJob;
  onOpen: () => void;
}) {
  const phase = syncJobPhaseLabel(job);
  const elapsed = formatDuration(syncJobElapsedSeconds(job));
  const count =
    job.total !== null
      ? `${formatCount(job.current)}/${formatCount(job.total)}`
      : job.current > 0
        ? formatCount(job.current)
        : null;
  const tone = jobTone(job);
  const accessibleLabel = [
    job.kind === "evidence"
      ? t.syncJob.openEvidenceDetails
      : t.syncJob.openDetails,
    phase,
    countLabel(job),
    t.syncJob.elapsed(elapsed),
  ].join(". ");

  return (
    <button
      type="button"
      className="sync-job-compact"
      data-tone={tone}
      onClick={onOpen}
      aria-label={accessibleLabel}
      title={job.message || phase}
    >
      <span className="sync-status-dot" aria-hidden="true" />
      <span className="sync-job-compact-copy">
        <span className="sync-job-compact-phase" aria-live="polite">
          {phase}
        </span>
        <span className="sync-job-compact-meta mono">
          {job.institute_code}
          {count !== null ? ` · ${count}` : ""} · {elapsed}
        </span>
      </span>
      <JobProgress job={job} compact />
    </button>
  );
}

/** Full persisted-job telemetry and terminal actions used by Components. */
export function SyncProgressPanel({
  controller,
  canRetry,
}: {
  controller: SyncJobController;
  canRetry: boolean;
}) {
  const { job, startError, pollError, start, dismiss } = controller;

  if (job === null) {
    if (startError === null) return null;
    return (
      <div className="sync-progress-panel" data-tone="error">
        <div className="sync-progress-head">
          <span className="sync-status-dot" aria-hidden="true" />
          <strong>{t.syncJob.failed}</strong>
          <button type="button" className="btn" onClick={dismiss}>
            {t.syncJob.dismiss}
          </button>
        </div>
        <p className="sync-job-error" role="alert">
          {startError}
        </p>
      </div>
    );
  }

  const phase = syncJobPhaseLabel(job);
  const tone = jobTone(job);
  const step = phaseStep(job);
  const active = isSyncJobActive(job);
  const elapsed = formatDuration(syncJobElapsedSeconds(job));
  const result = resultLabel(job);

  return (
    <section
      className="sync-progress-panel"
      data-tone={tone}
      aria-labelledby={`sync-job-${job.id}-title`}
    >
      <div className="sync-progress-head">
        <span className="sync-status-dot" aria-hidden="true" />
        <div className="sync-progress-title">
          <strong id={`sync-job-${job.id}-title`}>{jobTitle(job)}</strong>
          <span className="chip mono">{job.institute_code}</span>
        </div>
        <div className="sync-progress-times mono">
          <span>{t.syncJob.elapsed(elapsed)}</span>
          <span>{t.syncJob.lastUpdate(formatAge(job.updated_at))}</span>
        </div>
      </div>

      <div className="sync-progress-phase" aria-live="polite" aria-atomic="true">
        {phase}
      </div>
      <JobProgress job={job} />
      <div className="sync-progress-meta mono">
        <span>{countLabel(job)}</span>
        {step !== null && <span>{step}</span>}
      </div>

      {job.message !== "" && job.message !== phase && (
        <p className="sync-job-message">{job.message}</p>
      )}
      {pollError !== null && active && (
        <p className="sync-job-warning" role="status">
          {t.syncJob.connectionLost(pollError)}
        </p>
      )}
      {startError !== null && (
        <p className="sync-job-error" role="alert">
          {t.syncJob.retryFailed(startError)}
        </p>
      )}
      {job.status === "succeeded" && result !== null && (
        <p className="sync-job-result" role="status">
          {result}
        </p>
      )}
      {(job.status === "failed" || job.status === "interrupted") && (
        <p className="sync-job-error" role="alert">
          {job.error ?? phase} {t.syncJob.mirrorUnchanged}
        </p>
      )}

      {!active && (
        <div className="sync-progress-actions">
          {canRetry && (job.status === "failed" || job.status === "interrupted") && (
            <button
              type="button"
              className="btn primary"
              onClick={() => void start(job.institute_code)}
            >
              {t.syncJob.retry}
            </button>
          )}
          <button type="button" className="btn" onClick={dismiss}>
            {t.syncJob.dismiss}
          </button>
        </div>
      )}
    </section>
  );
}
