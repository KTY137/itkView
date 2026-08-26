import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  getMeasurementDimensions,
  getMeasurementSeries,
  getProductionStats,
  getStatsDimensions,
} from "../api";
import type {
  MeasurementDimensions,
  MeasurementSeries,
  ProductionStats,
  ProductionStatsQuery,
  StatsDimensions,
} from "../api";
import { makeDemoProductionStats, makeDemoStatsDimensions } from "../demoData";
import { formatCount, t } from "../i18n";
import {
  compactNumber,
  curveGeometry,
  defaultXResult,
  histogramBins,
} from "../measurements";
import StageLegend from "../StageLegend";
import { roleLabel, stageChipClass, stageLabel } from "../ui";

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

  const target = stageLabel(stats?.target_stage ?? "FINISHED");
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
                {roleLabel(ct)}
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

          <MeasurementsSection />
        </>
      )}
    </div>
  );
}

/** Mirrored measurement aggregation: every run of one result code in a single
 * chart. Which test types and result codes exist is discovered from the data
 * (hard rule #4) — nothing here knows what an "IV" test is called. */
function MeasurementsSection() {
  const [dims, setDims] = useState<MeasurementDimensions | null>(null);
  const [testType, setTestType] = useState<string>("");
  const [resultCode, setResultCode] = useState<string>("");
  const [xCode, setXCode] = useState<string>("");
  const [series, setSeries] = useState<MeasurementSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    getMeasurementDimensions(ctrl.signal)
      .then((data) => {
        setDims(data);
        const first = data.test_types[0];
        if (first !== undefined) {
          setTestType((current) => (current === "" ? first.test_type : current));
        }
      })
      .catch(() => setDims({ test_types: [] }));
    return () => ctrl.abort();
  }, []);

  const results = useMemo(
    () => dims?.test_types.find((entry) => entry.test_type === testType)?.results ?? [],
    [dims, testType],
  );

  useEffect(() => {
    if (results.length === 0) return;
    setResultCode((current) =>
      results.some((entry) => entry.code === current) ? current : results[0].code,
    );
  }, [results]);

  useEffect(() => {
    const picked = results.find((entry) => entry.code === resultCode);
    if (picked === undefined) return;
    setXCode(picked.kind === "array" ? (defaultXResult(results, resultCode) ?? "") : "");
  }, [results, resultCode]);

  useEffect(() => {
    if (testType === "" || resultCode === "") return;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    getMeasurementSeries(
      { test_type: testType, result: resultCode, x_result: xCode || undefined },
      ctrl.signal,
    )
      .then((data) => {
        setSeries(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) setSeries(null);
        else setError(errorMessage(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [testType, resultCode, xCode]);

  if (dims === null || dims.test_types.length === 0) return null;
  const arrayCodes = results.filter((entry) => entry.kind === "array");

  return (
    <section className="chart-card">
      <h2>{t.stats.measurementsTitle}</h2>
      <p className="state-note">{t.stats.measurementsSubtitle}</p>
      <div className="toolbar stats-filters">
        <label className="field">
          <span className="field-label">{t.stats.measurementTestLabel}</span>
          <select className="select-input" value={testType} onChange={(e) => setTestType(e.target.value)}>
            {dims.test_types.map((entry) => (
              <option key={entry.test_type} value={entry.test_type}>
                {entry.test_type}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t.stats.measurementResultLabel}</span>
          <select className="select-input" value={resultCode} onChange={(e) => setResultCode(e.target.value)}>
            {results.map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.name ?? entry.code}
              </option>
            ))}
          </select>
        </label>
        {series?.kind === "array" && arrayCodes.length > 1 && (
          <label className="field">
            <span className="field-label">{t.stats.measurementXLabel}</span>
            <select className="select-input" value={xCode} onChange={(e) => setXCode(e.target.value)}>
              <option value="">{t.stats.measurementXIndex}</option>
              {arrayCodes
                .filter((entry) => entry.code !== resultCode)
                .map((entry) => (
                  <option key={entry.code} value={entry.code}>
                    {entry.name ?? entry.code}
                  </option>
                ))}
            </select>
          </label>
        )}
      </div>

      {error !== null ? (
        <p className="state-note">{`${t.stats.measurementLoadError}: ${error}`}</p>
      ) : loading || series === null ? (
        <p className="state-note">{t.common.loading}</p>
      ) : series.kind === "array" && series.curves.length > 0 ? (
        <CurveOverlay series={series} />
      ) : series.kind === "scalar" && series.values.length > 0 ? (
        <ScalarDistribution series={series} />
      ) : (
        <p className="state-note">{t.stats.measurementEmpty}</p>
      )}
    </section>
  );
}

const CURVE_W = 640;
const CURVE_H = 260;

/** All runs of one array result overlaid. One recessive hue for the passed
 * population; failed runs use the reserved critical hue plus a dashed stroke
 * (identity never rides on colour alone) and both appear in the legend. */
function CurveOverlay({ series }: { series: MeasurementSeries }) {
  const geometry = useMemo(() => curveGeometry(series.curves, CURVE_W, CURVE_H), [series]);
  if (geometry === null) return <p className="state-note">{t.stats.measurementEmpty}</p>;
  const passed = series.curves.filter((curve) => curve.passed).length;
  const failed = series.curves.length - passed;
  const yLabel = series.result_name ?? series.result_code;
  const xLabel =
    series.x_result === null || series.curves.every((curve) => curve.x === null)
      ? t.stats.measurementXIndex
      : (series.x_name ?? series.x_result);

  return (
    <>
      <div className="curve-legend" aria-hidden="true">
        <span className="curve-key">
          <svg width="18" height="6">
            <line x1="0" y1="3" x2="18" y2="3" className="curve-line" />
          </svg>
          {t.stats.measurementPassed(passed)}
        </span>
        {failed > 0 && (
          <span className="curve-key">
            <svg width="18" height="6">
              <line x1="0" y1="3" x2="18" y2="3" className="curve-line failed" />
            </svg>
            {t.stats.measurementFailed(failed)}
          </span>
        )}
        <span className="curve-count">{t.stats.measurementCurves(series.curves.length)}</span>
      </div>
      <div className="curve-wrap">
        <svg
          viewBox={`-56 -8 ${CURVE_W + 72} ${CURVE_H + 40}`}
          className="curve-chart"
          role="img"
          aria-label={`${yLabel} vs ${xLabel} — ${t.stats.measurementCurves(series.curves.length)}`}
        >
          <g className="curve-grid">
            {[0.25, 0.5, 0.75].map((fraction) => (
              <line
                key={fraction}
                x1={0}
                x2={CURVE_W}
                y1={CURVE_H * fraction}
                y2={CURVE_H * fraction}
              />
            ))}
            <rect x={0} y={0} width={CURVE_W} height={CURVE_H} />
          </g>
          {series.curves.map((curve, index) => (
            <g key={curve.external_ref ?? `${curve.component_sn}-${index}`}>
              <polyline
                points={geometry.points[index]}
                className={curve.passed ? "curve-line" : "curve-line failed"}
              >
                <title>
                  {`${curve.local_name ?? curve.component_sn}${curve.measured_at ? ` · ${curve.measured_at.slice(0, 10)}` : ""}${curve.passed ? "" : " · failed"}`}
                </title>
              </polyline>
              {/* Wider invisible twin: an 8px hit target for the 2px line. */}
              <polyline points={geometry.points[index]} className="curve-hit">
                <title>
                  {`${curve.local_name ?? curve.component_sn}${curve.measured_at ? ` · ${curve.measured_at.slice(0, 10)}` : ""}${curve.passed ? "" : " · failed"}`}
                </title>
              </polyline>
            </g>
          ))}
          <g className="curve-axis" aria-hidden="true">
            <text x={-8} y={10} textAnchor="end">
              {compactNumber(geometry.yMax)}
            </text>
            <text x={-8} y={CURVE_H} textAnchor="end">
              {compactNumber(geometry.yMin)}
            </text>
            <text x={0} y={CURVE_H + 18} textAnchor="start">
              {compactNumber(geometry.xMin)}
            </text>
            <text x={CURVE_W} y={CURVE_H + 18} textAnchor="end">
              {compactNumber(geometry.xMax)}
            </text>
            <text x={CURVE_W / 2} y={CURVE_H + 34} textAnchor="middle" className="curve-axis-name">
              {xLabel}
            </text>
            <text
              x={-42}
              y={CURVE_H / 2}
              textAnchor="middle"
              className="curve-axis-name"
              transform={`rotate(-90 -42 ${CURVE_H / 2})`}
            >
              {yLabel}
            </text>
          </g>
        </svg>
      </div>
      {series.truncated && (
        <p className="state-note">{t.stats.measurementTruncated(series.curves.length)}</p>
      )}
    </>
  );
}

/** Scalar result: summary tiles plus an equal-width histogram. */
function ScalarDistribution({ series }: { series: MeasurementSeries }) {
  const bins = useMemo(() => histogramBins(series.values, 12), [series]);
  const summary = series.summary;
  return (
    <>
      {summary !== null && (
        <div className="metric-grid">
          <Metric label={t.stats.measurementCount} value={String(summary.count)} />
          <Metric label={t.stats.measurementMedian} value={compactNumber(summary.median)} />
          <Metric label={t.stats.measurementMean} value={compactNumber(summary.mean)} />
          <Metric
            label={t.stats.measurementSpread}
            value={`${compactNumber(summary.p25)} – ${compactNumber(summary.p75)}`}
          />
          <Metric
            label={t.stats.measurementRange}
            value={`${compactNumber(summary.min)} – ${compactNumber(summary.max)}`}
          />
        </div>
      )}
      <h3 className="field-label">{`${t.stats.measurementHistogram} — ${series.result_name ?? series.result_code}`}</h3>
      <VerticalBars
        data={bins.map((bin) => ({
          label: compactNumber((bin.start + bin.end) / 2),
          value: bin.count,
        }))}
        title={series.result_name ?? series.result_code}
      />
      {series.truncated && (
        <p className="state-note">{t.stats.measurementTruncated(series.values.length)}</p>
      )}
    </>
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
