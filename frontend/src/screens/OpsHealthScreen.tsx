import { useEffect, useState } from "react";
import { getOpsHealth } from "../api";
import type { Institute, OpsHealth, OpsHeartbeat, SyncJob } from "../api";
import { formatCount, formatDuration, formatRelative, formatTimestamp, t } from "../i18n";
import { product } from "../product";

type OpsTarget = "staged" | "triage" | "reminders";

type Props = {
  institutes: Institute[];
  selectedCode: string;
  allowAllInstitutes: boolean;
  onSelectedCodeChange: (code: string) => void;
  onNavigate: (target: OpsTarget) => void;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function heartbeatTone(status: OpsHeartbeat["status"]): string {
  if (status === "healthy") return "green";
  if (status === "disabled") return "muted";
  if (status === "missing" || status === "stale") return "amber";
  return "red";
}

function overallTone(status: OpsHealth["status"]): string {
  if (status === "healthy") return "green";
  if (status === "warning") return "amber";
  return "red";
}

function viewOverallStatus(health: OpsHealth): OpsHealth["status"] {
  const visibleHeartbeats = health.heartbeats.filter(
    (heartbeat) => heartbeat.service !== "outbox-worker",
  );
  if (visibleHeartbeats.some((heartbeat) => heartbeat.status === "error")) return "critical";
  if (
    health.sync.stale_active > 0 ||
    health.reminders.failed_occurrences > 0 ||
    visibleHeartbeats.some(
      (heartbeat) => heartbeat.status === "missing" || heartbeat.status === "stale",
    )
  ) {
    return "warning";
  }
  return "healthy";
}

function serviceLabel(service: OpsHeartbeat["service"]): string {
  return service === "outbox-worker"
    ? t.opsHealth.outboxWorker
    : t.opsHealth.reminderScheduler;
}

function syncName(job: SyncJob): string {
  return job.kind === "components" ? t.opsHealth.componentSync : t.opsHealth.evidenceSync;
}

/** Admin cockpit backed entirely by local database telemetry. */
export default function OpsHealthScreen({
  institutes,
  selectedCode,
  allowAllInstitutes,
  onSelectedCodeChange,
  onNavigate,
}: Props) {
  const [health, setHealth] = useState<OpsHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const visibleStatus =
    health === null || product.workflowWrites ? health?.status : viewOverallStatus(health);
  const visibleHeartbeats =
    health === null || product.workflowWrites
      ? (health?.heartbeats ?? [])
      : health.heartbeats.filter((heartbeat) => heartbeat.service !== "outbox-worker");

  useEffect(() => {
    const controller = new AbortController();
    let first = true;
    const load = () => {
      if (first) setLoading(true);
      setError(null);
      getOpsHealth(selectedCode || undefined, controller.signal)
        .then((snapshot) => {
          setHealth(snapshot);
          setLoading(false);
          first = false;
        })
        .catch((caught: unknown) => {
          if (controller.signal.aborted) return;
          setError(errorMessage(caught));
          setLoading(false);
          first = false;
        });
    };
    load();
    const timer = window.setInterval(load, 15_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [reloadKey, selectedCode]);

  return (
    <div className="screen ops-health-screen">
      <div className="sc-head">
        <h1>{t.opsHealth.title}</h1>
        <span className="sub">{t.opsHealth.subtitle}</span>
        {visibleStatus !== undefined && (
          <span className={`chip ${overallTone(visibleStatus)}`}>
            {t.opsHealth.overall[visibleStatus]}
          </span>
        )}
        <span className="cta">
          <button type="button" className="btn" onClick={() => setReloadKey((key) => key + 1)}>
            {t.opsHealth.refresh}
          </button>
        </span>
      </div>

      {(allowAllInstitutes || institutes.length > 1) && (
        <label className="phase4-field ops-health-scope">
          <span className="control-label">{t.opsHealth.instituteLabel}</span>
          <select
            className="select-input"
            value={selectedCode}
            onChange={(event) => onSelectedCodeChange(event.target.value)}
          >
            {allowAllInstitutes && <option value="">{t.opsHealth.allInstitutes}</option>}
            {institutes.map((institute) => (
              <option key={institute.code} value={institute.code}>
                {institute.code} · {institute.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <p className="phase4-copy ops-health-local-note">{t.opsHealth.localOnlyHint}</p>

      {health?.diagnostics_available === true && (
        <section className="panel ops-diagnostics" aria-labelledby="ops-diagnostics-title">
          <div>
            <h2 className="section-title" id="ops-diagnostics-title">
              {t.opsHealth.diagnosticsTitle}
            </h2>
            <p className="phase4-copy">{t.opsHealth.diagnosticsHint}</p>
          </div>
          <a className="btn" href="/api/ops/diagnostics" download>
            {t.opsHealth.downloadDiagnostics}
          </a>
        </section>
      )}

      {error !== null && (
        <div className="error-banner" role="alert">
          <span>{t.opsHealth.loadFailed(error)}</span>
          <button type="button" className="btn" onClick={() => setReloadKey((key) => key + 1)}>
            {t.common.retry}
          </button>
        </div>
      )}
      {loading && health === null && <p className="state-note">{t.common.loading}</p>}

      {health !== null && (
        <>
          <div className="metric-grid" aria-label={t.opsHealth.summaryLabel}>
            {product.workflowWrites && (
              <>
                <Metric
                  label={t.opsHealth.outboxBacklog}
                  value={health.outbox.backlog}
                  tone={health.outbox.failed > 0 ? "crit" : undefined}
                  hint={t.opsHealth.failedCount(health.outbox.failed)}
                />
                <Metric
                  label={t.opsHealth.attemptLimit}
                  value={health.outbox.at_attempt_limit}
                  tone={health.outbox.at_attempt_limit > 0 ? "crit" : undefined}
                />
              </>
            )}
            <Metric
              label={t.opsHealth.openReminderTasks}
              value={health.reminders.open_occurrences}
              tone={health.reminders.failed_occurrences > 0 ? "warn" : undefined}
              hint={t.opsHealth.failedCount(health.reminders.failed_occurrences)}
            />
            {product.workflowWrites && (
              <Metric
                label={t.opsHealth.parserIssues}
                value={health.ingest.parser_issues}
                tone={health.ingest.parser_issues > 0 ? "warn" : undefined}
                hint={t.opsHealth.triageCount(health.ingest.triage)}
              />
            )}
            <Metric
              label={t.opsHealth.activeSyncs}
              value={health.sync.active.length}
              tone={health.sync.stale_active > 0 ? "warn" : undefined}
              hint={t.opsHealth.staleCount(health.sync.stale_active)}
            />
            {product.workflowWrites && (
              <Metric
                label={t.opsHealth.oldestStaged}
                value={
                  health.outbox.oldest_open_age_seconds === null
                    ? t.common.none
                    : formatDuration(health.outbox.oldest_open_age_seconds)
                }
              />
            )}
          </div>

          <section className="panel phase4-detail ops-health-panel" aria-labelledby="ops-services">
            <div className="phase4-panel-head">
              <div>
                <h2 className="section-title" id="ops-services">
                  {t.opsHealth.servicesTitle}
                </h2>
                <p className="phase4-copy">{t.opsHealth.servicesHint}</p>
              </div>
              <span className="muted">
                {t.opsHealth.updated} {formatRelative(health.generated_at)}
              </span>
            </div>
            <div className="ops-heartbeat-grid">
              {visibleHeartbeats.map((heartbeat) => (
                <article className="ops-heartbeat" key={heartbeat.service}>
                  <div className="ops-heartbeat-head">
                    <strong>{serviceLabel(heartbeat.service)}</strong>
                    <span className={`chip ${heartbeatTone(heartbeat.status)}`}>
                      {t.opsHealth.heartbeatStatus[heartbeat.status]}
                    </span>
                  </div>
                  <dl className="ops-kv">
                    <dt>{t.opsHealth.lastHeartbeat}</dt>
                    <dd title={heartbeat.last_seen_at ? formatTimestamp(heartbeat.last_seen_at) : undefined}>
                      {heartbeat.last_seen_at ? formatRelative(heartbeat.last_seen_at) : t.common.none}
                    </dd>
                    <dt>{t.opsHealth.freshnessLimit}</dt>
                    <dd>{formatDuration(heartbeat.stale_after_seconds)}</dd>
                  </dl>
                </article>
              ))}
            </div>
          </section>

          <section className="panel phase4-detail ops-health-panel" aria-labelledby="ops-syncs">
            <div className="phase4-panel-head">
              <div>
                <h2 className="section-title" id="ops-syncs">
                  {t.opsHealth.syncTitle}
                </h2>
                <p className="phase4-copy">{t.opsHealth.syncHint}</p>
              </div>
            </div>
            {health.sync.latest.length === 0 ? (
              <p className="state-note">{t.opsHealth.noSyncHistory}</p>
            ) : (
              <div className="phase4-table-wrap">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>{t.opsHealth.syncKind}</th>
                      <th>{t.opsHealth.instituteLabel}</th>
                      <th>{t.opsHealth.statusLabel}</th>
                      <th>{t.opsHealth.lastUpdate}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {health.sync.latest.map((job) => (
                      <tr key={job.id}>
                        <td>{syncName(job)}</td>
                        <td className="mono">{job.institute_code}</td>
                        <td>
                          <span
                            className={`chip ${
                              job.status === "succeeded"
                                ? "green"
                                : job.status === "failed" || job.status === "interrupted"
                                  ? "red"
                                  : "amber"
                            }`}
                          >
                            {job.status}
                          </span>
                        </td>
                        <td title={formatTimestamp(job.updated_at)}>{formatRelative(job.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <div className="ops-action-grid">
            {product.workflowWrites && (
              <OpsAction
                title={t.opsHealth.stagedTitle}
                copy={t.opsHealth.stagedCopy(
                  health.outbox.backlog,
                  health.outbox.failed,
                  health.outbox.at_attempt_limit,
                )}
                label={t.opsHealth.openStaged}
                tone={health.outbox.at_attempt_limit > 0 ? "crit" : undefined}
                onClick={() => onNavigate("staged")}
              />
            )}
            {product.workflowWrites && (
              <OpsAction
                title={t.opsHealth.ingestTitle}
                copy={t.opsHealth.ingestCopy(
                  health.ingest.total,
                  health.ingest.parser_issues,
                  health.ingest.unassigned,
                )}
                label={t.opsHealth.openIngest}
                tone={health.ingest.parser_issues > 0 ? "warn" : undefined}
                onClick={() => onNavigate("triage")}
              />
            )}
            <OpsAction
              title={t.opsHealth.remindersTitle}
              copy={t.opsHealth.remindersCopy(
                health.reminders.active,
                health.reminders.open_occurrences,
                health.reminders.failed_occurrences,
                health.reminders.overdue,
              )}
              label={t.opsHealth.openReminders}
              tone={health.reminders.failed_occurrences > 0 ? "warn" : undefined}
              onClick={() => onNavigate("reminders")}
            />
          </div>
        </>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "warn" | "crit";
}) {
  return (
    <div className="metric-tile" data-tone={tone}>
      <span className="control-label">{label}</span>
      <span className="metric-value">{typeof value === "number" ? formatCount(value) : value}</span>
      {hint && <span className="metric-hint">{hint}</span>}
    </div>
  );
}

function OpsAction({
  title,
  copy,
  label,
  tone,
  onClick,
}: {
  title: string;
  copy: string;
  label: string;
  tone?: "warn" | "crit";
  onClick: () => void;
}) {
  return (
    <section className="panel phase4-detail ops-action" data-tone={tone}>
      <h2 className="section-title">{title}</h2>
      <p className="phase4-copy">{copy}</p>
      <button type="button" className="btn" onClick={onClick}>
        {label}
      </button>
    </section>
  );
}
