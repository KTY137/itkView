// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-2b249de08a10
import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  getProductionStats,
  getRequiredTestStats,
  getStatsDimensions,
} from "../api";
import type {
  MeasurementDimensions,
  MeasurementSeries,
  ProductionStats,
  ProductionStatsQuery,
  RequiredTestStageRow,
  RequiredTestStats,
  StatsDimensions,
} from "../api";
import { makeDemoProductionStats, makeDemoStatsDimensions } from "../demoData";
import { formatCount, t } from "../i18n";
import {
  loadMeasurementDimensions,
  loadMeasurementSeries,
} from "../measurementCache";
import {
  collectiveCurveCandidates,
  compactNumber,
  curveGeometry,
  defaultXResult,
  histogramBins,
  pairedCurves,
  representativeCurves,
} from "../measurements";
import type { CollectiveCurveFamily } from "../measurements";
import StageLegend from "../StageLegend";
import {
  readCollectiveDisplayMode,
  writeCollectiveDisplayMode,
} from "../statisticsPreferences";
import type { CollectiveDisplayMode } from "../statisticsPreferences";
import { roleLabel, stageChipClass, stageLabel } from "../ui";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const BUCKETS = [
  { id: "week", label: t.stats.bucketWeek },
  { id: "month", label: t.stats.bucketMonth },
  { id: "year", label: t.stats.bucketYear },
] as const;

export default function StatisticsScreen({
  measurementRevision = "unknown",
  measurementCacheScope = "default",
  instituteCode,
}: {
  measurementRevision?: string;
  measurementCacheScope?: string;
  instituteCode?: string;
}) {
  const [dims, setDims] = useState<StatsDimensions | null>(null);
  const [componentType, setComponentType] = useState("MODULE");
  const [typeCode, setTypeCode] = useState("");
  const [bucket, setBucket] = useState("month");
  const [stats, setStats] = useState<ProductionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [requiredTests, setRequiredTests] = useState<RequiredTestStats | null>(null);
  const [requiredTestsLoading, setRequiredTestsLoading] = useState(true);
  const [requiredTestsError, setRequiredTestsError] = useState<string | null>(null);
  const [requiredTestsReloadKey, setRequiredTestsReloadKey] = useState(0);

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

  useEffect(() => {
    const ctrl = new AbortController();
    setRequiredTests(null);
    setRequiredTestsLoading(true);
    setRequiredTestsError(null);
    getRequiredTestStats(instituteCode, ctrl.signal)
      .then((data) => {
        setRequiredTests(data);
        setRequiredTestsLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setRequiredTestsError(errorMessage(err));
        setRequiredTestsLoading(false);
      });
    return () => ctrl.abort();
  }, [instituteCode, requiredTestsReloadKey]);

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

          <RequiredTestsCard
            data={requiredTests}
            loading={requiredTestsLoading}
            error={requiredTestsError}
            onRetry={() => setRequiredTestsReloadKey((key) => key + 1)}
          />

          <MeasurementsSection
            revision={measurementRevision}
            cacheScope={measurementCacheScope}
          />
        </>
      )}
    </div>
  );
}

function requiredCoverage(row: RequiredTestStageRow): number | null {
  if (row.component_total === 0) return null;
  return Math.round((row.passed / row.component_total) * 100);
}

/** Server-owned stage-gate semantics, displayed without guessing which tests
 * or stages matter. Counts and cohort come straight from the profile-backed
 * endpoint. */
function RequiredTestsCard({
  data,
  loading,
  error,
  onRetry,
}: {
  data: RequiredTestStats | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <section className="chart-card required-tests-card" aria-labelledby="required-tests-title">
      <h2 id="required-tests-title">{t.stats.requiredTestsTitle}</h2>
      <p className="state-note">{t.stats.requiredTestsSubtitle}</p>
      {data !== null && (
        <p className="state-note">{t.stats.requiredTestsCohort(data.institute)}</p>
      )}
      {loading ? (
        <p className="state-note" role="status">{t.common.loading}</p>
      ) : error !== null ? (
        <div className="error-banner" role="alert">
          <span>{`${t.stats.requiredTestsLoadError}: ${error}`}</span>
          <button type="button" className="btn" onClick={onRetry}>
            {t.common.retry}
          </button>
        </div>
      ) : data === null || data.rows.length === 0 ? (
        <p className="state-note">{t.stats.requiredTestsEmpty}</p>
      ) : (
        <div className="required-tests-scroll">
          <table className="data-table required-tests-table">
            <thead>
              <tr>
                <th scope="col">{t.stats.requiredTestsStage}</th>
                <th scope="col">{t.stats.requiredTestsTest}</th>
                <th scope="col">{t.stats.requiredTestsComponents}</th>
                <th scope="col">{t.stats.requiredTestsPassed}</th>
                <th scope="col">{t.stats.requiredTestsFailed}</th>
                <th scope="col">{t.stats.requiredTestsMissing}</th>
                <th scope="col">{t.stats.requiredTestsCoverage}</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => {
                const coverage = requiredCoverage(row);
                const aria = t.stats.requiredTestsCoverageAria(
                  row.test_type,
                  stageLabel(row.stage),
                  row.passed,
                  row.failed,
                  row.missing,
                  row.component_total,
                );
                return (
                  <tr key={`${row.stage}:${row.test_type}`}>
                    <td>
                      <span className={stageChipClass(row.stage)}>{stageLabel(row.stage)}</span>
                    </td>
                    <td className="mono">{row.test_type}</td>
                    <td className="mono">{formatCount(row.component_total)}</td>
                    <td>
                      <span className={row.passed > 0 ? "chip green" : "chip neutral"}>
                        {formatCount(row.passed)}
                      </span>
                    </td>
                    <td>
                      <span className={row.failed > 0 ? "chip red" : "chip neutral"}>
                        {formatCount(row.failed)}
                      </span>
                    </td>
                    <td>
                      <span className={row.missing > 0 ? "chip amber" : "chip neutral"}>
                        {formatCount(row.missing)}
                      </span>
                    </td>
                    <td>
                      <div className="required-coverage-cell">
                        <span className="mono">
                          {coverage === null ? t.common.none : `${coverage} %`}
                        </span>
                        <div className="required-coverage-bar" role="img" aria-label={aria}>
                          {row.component_total > 0 && (
                            <>
                              <span
                                className="passed"
                                style={{ width: `${(row.passed / row.component_total) * 100}%` }}
                                aria-hidden="true"
                              />
                              <span
                                className="failed"
                                style={{ width: `${(row.failed / row.component_total) * 100}%` }}
                                aria-hidden="true"
                              />
                              <span
                                className="missing"
                                style={{ width: `${(row.missing / row.component_total) * 100}%` }}
                                aria-hidden="true"
                              />
                            </>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Measurement dimensions are loaded once for the explicit IV/CV panels and
 * the generic explorer. Every dataset and result code still comes from the
 * local mirror; the screen carries no institute-specific test map. */
function MeasurementsSection({
  revision,
  cacheScope,
}: {
  revision: string;
  cacheScope: string;
}) {
  const [dims, setDims] = useState<MeasurementDimensions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = loadMeasurementDimensions(cacheScope, revision);
    setDims(load.cached);
    setError(null);
    if (load.refresh === null) return;
    load.refresh
      .then((data) => {
        if (!active) return;
        setDims(data);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(errorMessage(err));
      });
    return () => {
      active = false;
    };
  }, [cacheScope, revision]);

  return (
    <>
      {dims !== null && (
        <MeasurementExplorer
          dimensions={dims}
          revision={revision}
          cacheScope={cacheScope}
        />
      )}
      <section aria-labelledby="collective-curves-title">
        <h2 className="section-title" id="collective-curves-title">
          {t.stats.collectiveCurvesTitle}
        </h2>
        <p className="state-note">{t.stats.collectiveCurvesSubtitle}</p>
        {error !== null && (
          <p className="sr-only" role="alert">
            {`${t.stats.measurementLoadError}: ${error}`}
          </p>
        )}
        <div className="charts">
          <CollectiveCurveCard
            family="iv"
            dimensions={dims}
            dimensionsError={error}
            revision={revision}
            cacheScope={cacheScope}
          />
          <CollectiveCurveCard
            family="cv"
            dimensions={dims}
            dimensionsError={error}
            revision={revision}
            cacheScope={cacheScope}
          />
        </div>
      </section>
    </>
  );
}

function CollectiveCurveCard({
  family,
  dimensions,
  dimensionsError,
  revision,
  cacheScope,
}: {
  family: CollectiveCurveFamily;
  dimensions: MeasurementDimensions | null;
  dimensionsError: string | null;
  revision: string;
  cacheScope: string;
}) {
  const candidates = useMemo(
    () => (dimensions === null ? [] : collectiveCurveCandidates(dimensions, family)),
    [dimensions, family],
  );
  const [selectedKey, setSelectedKey] = useState("");
  const selected =
    candidates.find((candidate) => candidate.testType === selectedKey) ?? candidates[0];
  const [series, setSeries] = useState<MeasurementSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [displayMode, setDisplayMode] = useState<CollectiveDisplayMode>(() =>
    readCollectiveDisplayMode(family),
  );

  useEffect(() => {
    if (selected === undefined) {
      setSeries(null);
      setError(null);
      setLoading(false);
      return;
    }
    let active = true;
    const query = {
      test_type: selected.testType,
      result: selected.yResult.code,
      x_result: selected.xResult.code,
    };
    const load = loadMeasurementSeries(cacheScope, revision, query);
    setSeries(load.cached);
    setError(null);
    setLoading(load.cached === null && load.refresh !== null);
    if (load.refresh === null) return;
    load.refresh
      .then((data) => {
        if (!active) return;
        setSeries(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [cacheScope, revision, selected?.testType, selected?.xResult.code, selected?.yResult.code]);

  const title = family === "iv" ? t.stats.collectiveIvTitle : t.stats.collectiveCvTitle;
  const subtitle =
    family === "iv" ? t.stats.collectiveIvSubtitle : t.stats.collectiveCvSubtitle;
  const empty = family === "iv" ? t.stats.collectiveIvEmpty : t.stats.collectiveCvEmpty;
  const paired = useMemo(() => pairedCurves(series?.curves ?? []), [series]);
  const displayed = useMemo(
    () => (displayMode === "all" ? paired : representativeCurves(paired)),
    [displayMode, paired],
  );
  const excluded = (series?.curves.length ?? 0) - paired.length;
  const returnedRunCount = series?.curves.length ?? 0;
  // Keep the collective cap notice outside CurveOverlay so it remains visible
  // even when every returned run is excluded before a plot can render.
  const pairedSeries = series === null ? null : { ...series, curves: displayed, truncated: false };

  return (
    <section className="chart-card">
      <h2>{title}</h2>
      <p className="state-note">{subtitle}</p>
      {dimensionsError !== null && dimensions === null ? (
        <p className="state-note">
          {`${t.stats.measurementLoadError}: ${dimensionsError}`}
        </p>
      ) : dimensions === null ? (
        <p className="state-note" role="status">{t.common.loading}</p>
      ) : selected === undefined ? (
        <p className="state-note">{empty}</p>
      ) : (
        <>
          <div className="toolbar stats-filters">
            <label className="field">
              <span className="field-label">{t.stats.collectiveDatasetLabel}</span>
              <select
                className="select-input"
                value={selected.testType}
                onChange={(event) => setSelectedKey(event.target.value)}
              >
                {candidates.map((candidate) => (
                  <option key={candidate.testType} value={candidate.testType}>
                    {candidate.testType}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">{t.stats.collectiveDisplayLabel}</span>
              <select
                className="select-input"
                value={displayMode}
                onChange={(event) => {
                  const mode = event.target.value === "all" ? "all" : "representative";
                  setDisplayMode(mode);
                  writeCollectiveDisplayMode(family, mode);
                }}
              >
                <option value="representative">{t.stats.collectiveRepresentative}</option>
                <option value="all">{t.stats.collectiveAllReturned}</option>
              </select>
            </label>
          </div>
          <p className="state-note">
            {t.stats.collectivePairing(selected.yResult.code, selected.xResult.code)}
          </p>
          {series !== null && (
            <p className="state-note">
              {displayMode === "all"
                ? t.stats.collectiveAllCount(displayed.length, paired.length, returnedRunCount)
                : t.stats.collectiveRepresentativeCount(
                    displayed.length,
                    paired.length,
                    returnedRunCount,
                  )}
            </p>
          )}
          {error !== null && pairedSeries === null ? (
            <p className="state-note" role="alert">
              {`${t.stats.measurementLoadError}: ${error}`}
            </p>
          ) : loading || pairedSeries === null ? (
            <p className="state-note" role="status">{t.common.loading}</p>
          ) : pairedSeries.kind === "array" && paired.length > 0 ? (
            <CurveOverlay series={pairedSeries} />
          ) : (
            <p className="state-note">{t.stats.collectiveNoPairedRuns}</p>
          )}
          {error !== null && pairedSeries !== null && (
            <p className="state-note" role="alert">
              {`${t.stats.measurementRefreshError}: ${error}`}
            </p>
          )}
          {excluded > 0 && (
            <p className="state-note">{t.stats.collectiveExcluded(excluded)}</p>
          )}
          {series?.truncated && (
            <p className="state-note">{t.stats.collectiveTruncated(returnedRunCount)}</p>
          )}
        </>
      )}
      {dimensionsError !== null && dimensions !== null && (
        <p className="state-note" role="alert">
          {`${t.stats.measurementRefreshError}: ${dimensionsError}`}
        </p>
      )}
    </section>
  );
}

/** Generic measurement explorer. Cached data paints immediately; a changed
 * mirror revision refreshes the selected aggregation once in the background. */
function MeasurementExplorer({
  dimensions: dims,
  revision,
  cacheScope,
}: {
  dimensions: MeasurementDimensions;
  revision: string;
  cacheScope: string;
}) {
  const [testType, setTestType] = useState<string>("");
  const [resultCode, setResultCode] = useState<string>("");
  const [xSelection, setXSelection] = useState({ key: "", code: "" });
  const [series, setSeries] = useState<MeasurementSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const first = dims.test_types[0];
    setTestType((current) =>
      first === undefined
        ? ""
        : dims.test_types.some((entry) => entry.test_type === current)
          ? current
          : first.test_type,
    );
  }, [dims]);

  const results = useMemo(
    () => dims.test_types.find((entry) => entry.test_type === testType)?.results ?? [],
    [dims, testType],
  );
  const arrayCodes = useMemo(
    () => results.filter((entry) => entry.kind === "array"),
    [results],
  );
  const selectionKey = JSON.stringify([testType, resultCode]);

  useEffect(() => {
    if (results.length === 0) {
      setResultCode("");
      setSeries(null);
      return;
    }
    setResultCode((current) =>
      results.some((entry) => entry.code === current) ? current : results[0].code,
    );
  }, [results]);

  useEffect(() => {
    const picked = results.find((entry) => entry.code === resultCode);
    setXSelection((current) => {
      if (picked === undefined) return { key: "", code: "" };
      const currentStillValid =
        current.key === selectionKey &&
        (current.code === "" ||
          arrayCodes.some((entry) => entry.code === current.code && entry.code !== resultCode));
      return {
        key: selectionKey,
        code: currentStillValid
          ? current.code
          : picked.kind === "array"
            ? (defaultXResult(results, resultCode) ?? "")
            : "",
      };
    });
  }, [arrayCodes, results, resultCode, selectionKey]);

  const xCode = xSelection.key === selectionKey ? xSelection.code : "";

  useEffect(() => {
    if (
      testType === "" ||
      resultCode === "" ||
      xSelection.key !== selectionKey ||
      !results.some((entry) => entry.code === resultCode)
    ) {
      return;
    }
    let active = true;
    const query = {
      test_type: testType,
      result: resultCode,
      x_result: xCode || undefined,
    };
    const load = loadMeasurementSeries(cacheScope, revision, query);
    setSeries(load.cached);
    setLoading(load.cached === null && load.refresh !== null);
    setError(null);
    if (load.refresh === null) return;
    load.refresh
      .then((data) => {
        if (!active) return;
        setSeries(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [cacheScope, revision, results, selectionKey, testType, resultCode, xCode, xSelection.key]);

  return (
    <section className="chart-card">
      <h2>{t.stats.measurementsTitle}</h2>
      <p className="state-note">{t.stats.measurementsSubtitle}</p>
      {dims.test_types.length === 0 ? (
        <p className="state-note">{t.stats.measurementEmpty}</p>
      ) : (
        <>
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
                <select
                  className="select-input"
                  value={xCode}
                  onChange={(event) =>
                    setXSelection({ key: selectionKey, code: event.target.value })
                  }
                >
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

          {error !== null && series === null ? (
            <p className="state-note" role="alert">
              {`${t.stats.measurementLoadError}: ${error}`}
            </p>
          ) : loading || series === null ? (
            <p className="state-note" role="status">{t.common.loading}</p>
          ) : series.kind === "array" && series.curves.length > 0 ? (
            <CurveOverlay series={series} />
          ) : series.kind === "scalar" && series.values.length > 0 ? (
            <ScalarDistribution series={series} />
          ) : (
            <p className="state-note">{t.stats.measurementEmpty}</p>
          )}
          {error !== null && series !== null && (
            <p className="state-note" role="alert">
              {`${t.stats.measurementRefreshError}: ${error}`}
            </p>
          )}
        </>
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
      <div className="curve-legend">
        <span className="curve-key">
          <svg width="18" height="6" aria-hidden="true" focusable="false">
            <line x1="0" y1="3" x2="18" y2="3" className="curve-line" />
          </svg>
          {t.stats.measurementPassed(passed)}
        </span>
        {failed > 0 && (
          <span className="curve-key">
            <svg width="18" height="6" aria-hidden="true" focusable="false">
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
          aria-label={`${yLabel} vs ${xLabel} — ${t.stats.measurementCurves(series.curves.length)}; ${t.stats.measurementPassed(passed)}; ${t.stats.measurementFailed(failed)}`}
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
