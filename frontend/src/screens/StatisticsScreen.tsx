import { useEffect, useState } from "react";
import { ApiError, getProductionStats, getStatsDimensions } from "../api";
import type { ProductionStats, ProductionStatsQuery, StatsDimensions } from "../api";
import { makeDemoProductionStats, makeDemoStatsDimensions } from "../demoData";
import { formatCount, t } from "../i18n";
import StageLegend from "../StageLegend";
import { stageChipClass, stageLabel } from "../ui";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const BUCKETS = [
  { id: "week", label: t.stats.bucketWeek },
  { id: "month", label: t.stats.bucketMonth },
  { id: "year", label: t.stats.bucketYear },
] as const;

export default function StatisticsScreen() {
  const [dims, setDims] = useState<StatsDimensions | null>(null);
  const [componentType, setComponentType] = useState("MODULE");
  const [typeCode, setTypeCode] = useState("");
  const [bucket, setBucket] = useState("month");
  const [stats, setStats] = useState<ProductionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    getStatsDimensions(ctrl.signal)
      .then(setDims)
      .catch(() => setDims(makeDemoStatsDimensions()));
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    const query: ProductionStatsQuery = { component_type: componentType, bucket };
    if (typeCode !== "") query.type_code = typeCode;
    getProductionStats(query, ctrl.signal)
      .then((data) => {
        setStats(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setStats(makeDemoProductionStats());
          setDemo(true);
        } else {
          setError(errorMessage(err));
        }
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [componentType, typeCode, bucket, reloadKey]);

  if (error !== null) {
    return (
      <div className="screen">
        <div className="error-banner" role="alert">
          <span>
            {t.stats.loadError}: {error}
          </span>
          <button type="button" className="btn" onClick={() => setReloadKey((key) => key + 1)}>
            {t.common.retry}
          </button>
        </div>
      </div>
    );
  }

  const target = stats?.target_stage ?? "FINISHED";
  const lead = stats?.lead_time;

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.statistics}</h1>
        <span className="sub">{t.stats.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>

      <div className="toolbar stats-filters">
        <label className="field">
          <span className="field-label">{t.stats.filterType}</span>
          <select className="select-input" value={componentType} onChange={(e) => setComponentType(e.target.value)}>
            {(dims?.component_types ?? ["MODULE"]).map((ct) => (
              <option key={ct} value={ct}>
                {ct}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t.stats.filterTypeCode}</span>
          <select className="select-input" value={typeCode} onChange={(e) => setTypeCode(e.target.value)}>
            <option value="">{t.stats.allTypeCodes}</option>
            {(dims?.type_codes ?? []).map((tc) => (
              <option key={tc} value={tc}>
                {tc}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t.stats.filterBucket}</span>
          <select className="select-input" value={bucket} onChange={(e) => setBucket(e.target.value)}>
            {BUCKETS.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading || stats === null ? (
        <p className="state-note">{t.common.loading}</p>
      ) : (
        <>
          <StageLegend label={t.stats.stageFlow} />
          <div className="metric-grid">
            <Metric label={t.stats.componentsTracked} value={formatCount(stats.components_tracked)} />
            <Metric
              label={t.stats.yield}
              value={
                stats.yield_.rate === null
                  ? t.common.none
                  : `${Math.round(stats.yield_.rate * 100)} %`
              }
              hint={t.stats.yieldHint(
                stats.yield_.good,
                stats.yield_.concluded,
                stats.yield_.in_progress,
              )}
            />
            <Metric
              label={t.stats.completed(target)}
              value={String(lead?.count ?? 0)}
            />
            <Metric
              label={t.stats.leadTimeMedian(target)}
              value={lead?.median_days === null || lead === undefined
                ? t.common.none
                : `${lead.median_days} ${t.stats.days}`}
              hint={
                lead && lead.p25_days !== null && lead.p75_days !== null
                  ? `${t.stats.leadTimeSpread}: ${lead.p25_days}–${lead.p75_days} ${t.stats.days}`
                  : undefined
              }
            />
            <Metric
              label={t.stats.reworkRate}
              value={`${Math.round(stats.rework.rate * 100)} %`}
              hint={`${stats.rework.reworked_components}/${stats.rework.total_components}`}
            />
          </div>

          <section className="chart-card">
            <h2>{t.stats.throughput(target)}</h2>
            {stats.throughput.length === 0 ? (
              <p className="state-note">{t.stats.noneReached(target)}</p>
            ) : (
              <VerticalBars
                data={stats.throughput.map((p) => ({ label: p.period, value: p.count }))}
                title={t.stats.throughput(target)}
              />
            )}
          </section>

          <div className="charts">
            <section className="chart-card">
              <h2>{t.stats.stageDwell}</h2>
              {stats.stage_dwell.length === 0 ? (
                <p className="state-note">{t.stats.noDwell}</p>
              ) : (
                <HorizontalBars
                  unit={t.stats.days}
                  rows={stats.stage_dwell.map((d) => ({
                    label: d.stage,
                    value: d.median_days,
                    n: d.count,
                  }))}
                />
              )}
            </section>

            <section className="chart-card">
              <h2>{t.stats.reworkByStage}</h2>
              {stats.rework.by_stage.length === 0 ? (
                <p className="state-note">{t.stats.noRework}</p>
              ) : (
                <HorizontalBars
                  rows={stats.rework.by_stage.map((r) => ({ label: r.stage, value: r.count }))}
                />
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric-tile">
      <div className="field-label">{label}</div>
      <div className="metric-value">{value}</div>
      {hint !== undefined && <div className="metric-hint">{hint}</div>}
    </div>
  );
}

/** Single-series magnitude over time — one hue, value on the cap, no legend. */
function VerticalBars({ data, title }: { data: { label: string; value: number }[]; title: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const summary = data.map((d) => `${d.label}: ${d.value}`).join(", ");
  return (
    <>
      <div className="bars" role="img" aria-label={`${title} — ${summary}`}>
        {data.map((d) => (
          <div className="bar-g" key={d.label} title={`${d.label}: ${d.value}`}>
            <span className="v">{d.value}</span>
            <div className="bar" style={{ height: `${(d.value / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="bar-lbls" aria-hidden="true">
        {data.map((d) => (
          <span key={d.label} title={d.label}>
            {d.label}
          </span>
        ))}
      </div>
    </>
  );
}

/** Single-series magnitude per (stage) category — horizontal, so long stage
 * names stay legible. Bar is one hue; the stage identity is carried by a
 * colour-coded chip label, never by the bar colour alone. */
function HorizontalBars({
  rows,
  unit,
}: {
  rows: { label: string; value: number; n?: number }[];
  unit?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hbar-row" key={r.label}>
          <span className={stageChipClass(r.label)} title={r.label}>
            {stageLabel(r.label)}
          </span>
          <div className="hbar-track">
            <div className="hbar-fill" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
          <span className="hbar-val">
            {r.value}
            {unit !== undefined ? ` ${unit}` : ""}
            {r.n !== undefined ? <span className="hbar-n"> · n={r.n}</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}
