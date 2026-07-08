import { useEffect, useState } from "react";
import { ApiError, getDashboardSummary } from "../api";
import type { CountBucket, DashboardSummary } from "../api";
import { makeDemoDashboardSummary } from "../demoData";
import { formatTimestamp, t } from "../i18n";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function DashboardScreen() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    getDashboardSummary(ctrl.signal)
      .then((data) => {
        setSummary(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setSummary(makeDemoDashboardSummary());
          setDemo(true);
        } else {
          setError(errorMessage(err));
        }
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [reloadKey]);

  if (error !== null) {
    return (
      <div className="screen">
        <div className="error-banner" role="alert">
          <span>
            {t.dashboard.loadError}: {error}
          </span>
          <button className="btn" onClick={() => setReloadKey((key) => key + 1)}>
            {t.common.retry}
          </button>
        </div>
      </div>
    );
  }

  if (loading || summary === null) {
    return <p className="state-note">{t.common.loading}</p>;
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.dashboard}</h1>
        <span className="sub">{t.dashboard.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>
      {demo && (
        <div className="toolbar">
          <span className="muted">{t.common.demoNote}</span>
        </div>
      )}
      <div className="metric-grid">
        <Metric label={t.dashboard.totalComponents} value={String(summary.total_components)} />
        <Metric
          label={t.dashboard.lastSynced}
          value={
            summary.last_synced_at === null
              ? t.dashboard.noSyncYet
              : formatTimestamp(summary.last_synced_at)
          }
        />
        <Metric label={t.dashboard.submittedOutbox} value={String(summary.submitted_outbox)} />
        <Metric label={t.dashboard.failedOutbox} value={String(summary.failed_outbox)} />
      </div>
      <div className="charts">
        <BarChart title={t.dashboard.byStage} buckets={summary.by_stage} />
        <BarChart title={t.dashboard.outboxByStatus} buckets={summary.outbox_by_status} />
      </div>
      <div className="dashboard-grid">
        <BucketTable title={t.dashboard.byType} buckets={summary.by_component_type} />
        <BucketTable title={t.dashboard.byInstitute} buckets={summary.by_institute} />
      </div>
    </div>
  );
}

/**
 * Single-series magnitude chart (count per category). One hue (var(--series)),
 * so no legend is needed — the title names what is plotted. Each column carries
 * its value on the cap and a hover title; the bars container has an aria-label
 * so the data is legible without color, and the raw numbers also live in the
 * tables below.
 */
function BarChart({ title, buckets }: { title: string; buckets: CountBucket[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const summary = buckets.map((b) => `${b.label}: ${b.count}`).join(", ");
  return (
    <section className="chart-card">
      <h2>{title}</h2>
      {buckets.length === 0 ? (
        <p className="state-note">{t.dashboard.empty}</p>
      ) : (
        <>
          <div className="bars" role="img" aria-label={`${title} — ${summary}`}>
            {buckets.map((bucket) => (
              <div className="bar-g" key={bucket.label} title={`${bucket.label}: ${bucket.count}`}>
                <span className="v">{bucket.count}</span>
                <div className="bar" style={{ height: `${(bucket.count / max) * 100}%` }} />
              </div>
            ))}
          </div>
          <div className="bar-lbls" aria-hidden="true">
            {buckets.map((bucket) => (
              <span key={bucket.label} title={bucket.label}>
                {bucket.label}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <div className="field-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

function BucketTable({ title, buckets }: { title: string; buckets: CountBucket[] }) {
  return (
    <section className="panel dashboard-panel">
      <h2 className="section-title">{title}</h2>
      {buckets.length === 0 ? (
        <p className="state-note">{t.dashboard.empty}</p>
      ) : (
        <table className="data-table compact-table">
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.label}>
                <td className="mono">{bucket.label}</td>
                <td className="count-cell">{bucket.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
