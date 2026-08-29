// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-48c97b20807c
import { useEffect, useState } from "react";
import { ApiError, getDashboardSummary, getInstitutes } from "../api";
import type { CountBucket, DashboardSummary } from "../api";
import { makeDemoDashboardSummary } from "../demoData";
import { formatCount, formatRelative, formatTimestamp, t } from "../i18n";
import { product } from "../product";
import StageLegend from "../StageLegend";
import { stageLabel, stageTone, statusTone } from "../ui";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

type Tone = string;
type InstituteBrand = { logo?: string; icon: string };
type Row = { label: string; count: number; tone?: Tone; logo?: string; icon?: string };

export default function DashboardScreen() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [instituteBrands, setInstituteBrands] = useState<Record<string, InstituteBrand>>({});

  // Institute branding is profile data (hard rule #4).
  // logo_url or compact icon text; otherwise the code becomes a neutral badge.
  useEffect(() => {
    const ctrl = new AbortController();
    getInstitutes(ctrl.signal)
      .then((list) => {
        const map: Record<string, InstituteBrand> = {};
        for (const inst of list) {
          map[inst.code] = {
            logo: stringSetting(inst.settings, "logo_url", "logoUrl"),
            icon: normalizeInstituteIcon(
              stringSetting(
                inst.settings,
                "dashboard_icon",
                "icon_text",
                "short_code",
                "icon",
              ) ?? inst.code,
            ),
          };
        }
        setInstituteBrands(map);
      })
      .catch(() => setInstituteBrands({}));
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

  // Humanise the stage label but derive the tone from the raw code first.
  const stageRows: Row[] = summary.by_stage.map((b) => ({
    label: stageLabel(b.label),
    count: b.count,
    tone: stageTone(b.label),
  }));
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
        <Metric
          label={t.dashboard.oldestSync}
          value={
            summary.oldest_synced_at === null
              ? t.dashboard.noSyncYet
              : formatRelative(summary.oldest_synced_at)
          }
          title={
            summary.oldest_synced_at === null ? undefined : formatTimestamp(summary.oldest_synced_at)
          }
          tone={summary.stale_components > 0 ? "warn" : undefined}
        />
        <Metric
          label={t.dashboard.requiredTestGaps}
          value={formatCount(summary.required_test_gaps)}
          hint={t.dashboard.requiredTestGapHint(summary.components_with_test_gaps)}
          tone={summary.required_test_gaps > 0 ? "warn" : undefined}
        />
        <Metric
          label={t.dashboard.staleComponents}
          value={formatCount(summary.stale_components)}
          tone={summary.stale_components > 0 ? "warn" : undefined}
        />
        <Metric
          label={t.dashboard.trashedComponents}
          value={formatCount(summary.trashed_components)}
          tone={summary.trashed_components > 0 ? "crit" : undefined}
        />
        {product.workflowWrites && (
          <>
            <Metric
              label={t.dashboard.reviewOutbox}
              value={formatCount(summary.review_outbox)}
              tone={summary.review_outbox > 0 ? "warn" : undefined}
            />
            <Metric
              label={t.dashboard.approvedOutbox}
              value={formatCount(summary.approved_outbox)}
              tone={summary.approved_outbox > 0 ? "warn" : undefined}
            />
            <Metric
              label={t.dashboard.submittedOutbox}
              value={formatCount(summary.submitted_outbox)}
              tone={summary.submitted_outbox > 0 ? "warn" : undefined}
            />
            <Metric
              label={t.dashboard.failedOutbox}
              value={formatCount(summary.failed_outbox)}
              tone={summary.failed_outbox > 0 ? "crit" : undefined}
            />
          </>
        )}
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
        {product.workflowWrites && (
          <section className="chart-card">
            <h2>{t.dashboard.outboxByStatus}</h2>
            <ToneBars rows={statusRows} empty={t.dashboard.empty} />
          </section>
        )}
        <section className="chart-card">
          <h2>{t.dashboard.byInstitute}</h2>
          <ToneBars
            rows={summary.by_institute.map((b) => ({
              ...b,
              logo: instituteBrands[b.label]?.logo,
              icon: instituteBrands[b.label]?.icon ?? normalizeInstituteIcon(b.label),
            }))}
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

function stringSetting(settings: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = settings[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  return undefined;
}

function normalizeInstituteIcon(value: string): string {
  const clean = value.trim().toUpperCase();
  if (clean === "") return "?";
  if (clean.length <= 5) return clean;
  const parts = clean.split(/[^A-Z0-9]+/).filter(Boolean);
  if (parts.length > 1) return parts.map((part) => part[0]).join("").slice(0, 5);
  const compact = clean.replace(/[^A-Z0-9]/g, "");
  return compact === "" ? "?" : compact.slice(0, 5);
}

function Metric({
  label,
  value,
  title,
  tone,
  hint,
}: {
  label: string;
  value: string;
  title?: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="metric-tile" data-tone={tone} title={title}>
      <div className="field-label">{label}</div>
      <div className="metric-value">{value}</div>
      {hint !== undefined && <div className="metric-hint">{hint}</div>}
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
            {r.logo !== undefined ? (
              <img className="hbar-logo" src={r.logo} alt="" />
            ) : (
              r.icon !== undefined && (
                <span className="hbar-icon" aria-hidden="true">
                  {r.icon}
                </span>
              )
            )}
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
