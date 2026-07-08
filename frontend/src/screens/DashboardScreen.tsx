import { useEffect, useState } from "react";
import { ApiError, getDashboardSummary, getInstitutes } from "../api";
import type { CountBucket, DashboardSummary } from "../api";
import { makeDemoDashboardSummary } from "../demoData";
import { formatCount, formatRelative, formatTimestamp, t } from "../i18n";
import StageLegend from "../StageLegend";
import { stageTone, statusTone } from "../ui";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

type Tone = string;
type Row = { label: string; count: number; tone?: Tone; logo?: string };

export default function DashboardScreen() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [logos, setLogos] = useState<Record<string, string>>({});

  // Institute logos are profile data (hard rule #4) — map each code to its
  // configured logo_url so the "by institute" bars can carry the branding.
  useEffect(() => {
    const ctrl = new AbortController();
    getInstitutes(ctrl.signal)
      .then((list) => {
        const map: Record<string, string> = {};
        for (const inst of list) {
          const url = inst.settings?.logo_url;
          if (typeof url === "string" && url !== "") map[inst.code] = url;
        }
        setLogos(map);
      })
      .catch(() => setLogos({}));
    return () => ctrl.abort();
  }, []);

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
          <button type="button" className="btn" onClick={() => setReloadKey((key) => key + 1)}>
            {t.common.retry}
          </button>
        </div>
      </div>
    );
  }

  if (loading || summary === null) {
    return <p className="state-note">{t.common.loading}</p>;
  }

  const stageRows: Row[] = summary.by_stage.map((b) => ({ ...b, tone: stageTone(b.label) }));
  const statusRows: Row[] = summary.outbox_by_status.map((b) => ({
    ...b,
    tone: statusTone(b.label),
  }));
  // The type breakdown is long (20+ types at a real institute); keep the top 8
  // and roll the rest into "other" so the card stays scannable.
  const typeRows = topN(summary.by_component_type, 8);

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
        <Metric label={t.dashboard.totalComponents} value={formatCount(summary.total_components)} />
        <Metric
          label={t.dashboard.lastSynced}
          value={
            summary.last_synced_at === null
              ? t.dashboard.noSyncYet
              : formatRelative(summary.last_synced_at)
          }
          title={
            summary.last_synced_at === null ? undefined : formatTimestamp(summary.last_synced_at)
          }
        />
        <Metric label={t.dashboard.submittedOutbox} value={formatCount(summary.submitted_outbox)} />
        <Metric
          label={t.dashboard.failedOutbox}
          value={formatCount(summary.failed_outbox)}
          tone={summary.failed_outbox > 0 ? "crit" : undefined}
        />
      </div>

      <section className="chart-card">
        <div className="card-head">
          <h2>{t.dashboard.byStage}</h2>
          <StageLegend label={t.stats.stageFlow} />
        </div>
        <ToneBars rows={stageRows} empty={t.dashboard.empty} />
      </section>

      <div className="dashboard-grid">
        <section className="chart-card">
          <h2>{t.dashboard.byType}</h2>
          <ToneBars rows={typeRows} empty={t.dashboard.empty} />
        </section>
        <section className="chart-card">
          <h2>{t.dashboard.outboxByStatus}</h2>
          <ToneBars rows={statusRows} empty={t.dashboard.empty} />
        </section>
        <section className="chart-card">
          <h2>{t.dashboard.byInstitute}</h2>
          <ToneBars
            rows={summary.by_institute.map((b) => ({ ...b, logo: logos[b.label] }))}
            empty={t.dashboard.empty}
          />
        </section>
      </div>
    </div>
  );
}

function topN(buckets: CountBucket[], n: number): Row[] {
  if (buckets.length <= n) return buckets;
  const head = buckets.slice(0, n);
  const rest = buckets.slice(n).reduce((sum, b) => sum + b.count, 0);
  return rest > 0 ? [...head, { label: `+${buckets.length - n} other`, count: rest }] : head;
}

function Metric({ label, value, title, tone }: { label: string; value: string; title?: string; tone?: string }) {
  return (
    <div className="metric-tile" data-tone={tone} title={title}>
      <div className="field-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

/**
 * Horizontal magnitude bars, one row per category. A bar's fill takes its
 * category tone where one is given (stage ramp / status), so the chart reads
 * in the same colour language as the rest of the app; untoned rows fall back
 * to the single series hue. The category totals sit at the end, and an
 * aria-label carries the data for non-visual reads.
 */
function ToneBars({ rows, empty }: { rows: Row[]; empty: string }) {
  if (rows.length === 0) return <p className="state-note">{empty}</p>;
  const max = Math.max(1, ...rows.map((r) => r.count));
  const summary = rows.map((r) => `${r.label}: ${r.count}`).join(", ");
  return (
    <div className="hbars" role="img" aria-label={summary}>
      {rows.map((r) => (
        <div className="hbar-row" key={r.label}>
          <span className="hbar-cat" title={r.label}>
            {r.logo !== undefined && <img className="hbar-logo" src={r.logo} alt="" />}
            <span className="hbar-cat-text">{r.label}</span>
          </span>
          <div className="hbar-track">
            <div
              className="hbar-fill"
              data-tone={r.tone}
              style={{ width: `${(r.count / max) * 100}%` }}
            />
          </div>
          <span className="hbar-val">{formatCount(r.count)}</span>
        </div>
      ))}
    </div>
  );
}
