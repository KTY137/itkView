/**
 * Mirrored PDB test runs with their measured values.
 *
 * Everything here reads the local mirror, never the PDB: opening a module must
 * not wait on a network round trip. An empty section therefore means "nothing
 * mirrored yet" and says so, rather than implying the tests do not exist.
 *
 * Values arrive keyed by PDB code (`GW_GLUE_H1`) with their description
 * alongside (`Weight of glue under hybrid 1 [g]`). The description is what
 * carries the unit, so it is always preferred for the label and the code is
 * kept as the title attribute for anyone who works in PDB codes.
 */

import { useEffect, useState } from "react";

import {
  ApiError,
  componentAttachmentUrl,
  getComponentTests,
  type ComponentPreviewTest,
  type TestRunAttachment,
  type TestRunDetail,
} from "./api";
import { t } from "./i18n";
import { isDisplayableImage } from "./ui";
import ImageLightbox from "./ImageLightbox";

export type DisplayTestRun = TestRunDetail | ComponentPreviewTest;

function isGhostRun(run: DisplayTestRun): run is ComponentPreviewTest {
  return "ghost" in run && run.ghost;
}

/** A measured value that is a numeric array — an IV sweep and friends. */
function asNumericArray(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  const numbers = value.filter((entry): entry is number => typeof entry === "number");
  return numbers.length === value.length ? numbers : null;
}

/** Exported so the worksheet's compact values cell (ModuleWorksheet.tsx)
 * formats a measured value identically instead of keeping a second, drifting
 * copy of this logic (review finding M4). */
export function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return t.testResults.valueMissing;
  if (typeof value === "number") {
    // Instrument values are small decimals; trim the float noise without
    // rounding a genuine 0.1664 down to something that looks measured.
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
  }
  if (typeof value === "boolean") return value ? t.common.yes : t.common.no;
  return String(value);
}

/**
 * A dict-valued result: per-position measurements keyed by position name, e.g.
 * MODULE_METROLOGY's `{"ABC_R5H1_0": 2.1064, …}` or MODULE_WIRE_BONDING's
 * per-site counts. Not an array, not a scalar — `formatScalar` would stringify
 * one to the literal "[object Object]" and lose every measured value.
 */
function asMap(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asFinitePair(value: unknown): readonly [number, number] | null {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    typeof value[0] !== "number" ||
    typeof value[1] !== "number" ||
    !Number.isFinite(value[0]) ||
    !Number.isFinite(value[1])
  ) {
    return null;
  }
  return [value[0], value[1]];
}

/**
 * A value nested inside a map cell. Scalars read exactly as they do anywhere
 * else; a container gets its extent instead of `String(value)`, reusing the
 * worksheet's chip wording so both surfaces describe extent identically.
 */
function formatNestedValue(value: unknown): string {
  const pair = asFinitePair(value);
  if (pair !== null) {
    return t.testResults.numericPair(formatScalar(pair[0]), formatScalar(pair[1]));
  }
  if (Array.isArray(value)) return t.worksheet.arrayPoints(value.length);
  const nested = asMap(value);
  if (nested !== null) return t.worksheet.mapEntries(Object.keys(nested).length);
  return formatScalar(value);
}

/** The measured per-position values of a dict result, spelled out.
 *
 * The compact worksheet row shows only "⌁ 3 entries"; the expanded detail is
 * where the operator comes for the values themselves, so they are rendered in
 * full here rather than summarised a second time. An empty map says "⌁ 0
 * entries" — honestly empty, never "[object Object]".
 */
function MapValue({ entries }: { entries: Record<string, unknown> }) {
  const pairs = Object.entries(entries);
  if (pairs.length === 0) {
    return <span className="muted">{t.worksheet.mapEntries(0)}</span>;
  }
  return (
    <dl className="measure-grid">
      {pairs.map(([position, value]) => (
        <div className="measure" key={position}>
          <dt title={position}>{position}</dt>
          <dd className={value === null || value === undefined ? "muted" : "mono"}>
            {formatNestedValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function formatTimestamp(value: string | null): string {
  if (value === null) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** A minimal inline curve. No chart library: one polyline, its own axes. */
function CurvePlot({ xs, ys, xLabel, yLabel }: {
  xs: number[];
  ys: number[];
  xLabel: string;
  yLabel: string;
}) {
  const width = 320;
  const height = 150;
  const pad = { left: 38, right: 8, top: 10, bottom: 24 };

  const count = Math.min(xs.length, ys.length);
  const xMin = Math.min(...xs.slice(0, count));
  const xMax = Math.max(...xs.slice(0, count));
  const yMin = Math.min(...ys.slice(0, count));
  const yMax = Math.max(...ys.slice(0, count));
  // A flat curve would divide by zero; give it a nominal span instead.
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;

  const points: string[] = [];
  for (let index = 0; index < count; index += 1) {
    const x = pad.left + ((xs[index] - xMin) / xSpan) * (width - pad.left - pad.right);
    const y = height - pad.bottom - ((ys[index] - yMin) / ySpan) * (height - pad.top - pad.bottom);
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }

  return (
    <figure className="curve">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${yLabel} over ${xLabel}`}>
        <line
          className="curve-axis"
          x1={pad.left}
          y1={height - pad.bottom}
          x2={width - pad.right}
          y2={height - pad.bottom}
        />
        <line
          className="curve-axis"
          x1={pad.left}
          y1={pad.top}
          x2={pad.left}
          y2={height - pad.bottom}
        />
        <polyline className="curve-line" points={points.join(" ")} />
        <text className="curve-tick" x={pad.left} y={height - 8} textAnchor="start">
          {formatScalar(xMin)}
        </text>
        <text className="curve-tick" x={width - pad.right} y={height - 8} textAnchor="end">
          {formatScalar(xMax)}
        </text>
        <text className="curve-tick" x={pad.left - 4} y={pad.top + 8} textAnchor="end">
          {formatScalar(yMax)}
        </text>
        <text className="curve-tick" x={pad.left - 4} y={height - pad.bottom} textAnchor="end">
          {formatScalar(yMin)}
        </text>
      </svg>
      <figcaption>
        {yLabel} / {xLabel} · {t.testResults.curvePoints(count)}
      </figcaption>
    </figure>
  );
}

type MapPlotData = { keys: string[]; values: number[] };

/**
 * A map is plotted only when every entry has one unambiguous numeric shape.
 * Mixed maps and numeric-pair maps stay tables: coercing or assigning axes to
 * those values would fabricate data. Plain finite numbers are categorical
 * values keyed by the map entry.
 */
function mapPlotData(entries: Record<string, unknown>): MapPlotData | null {
  const pairs = Object.entries(entries);
  if (pairs.length === 0) return null;

  if (pairs.every(([, value]) => typeof value === "number" && Number.isFinite(value))) {
    return {
      keys: pairs.map(([key]) => key),
      values: pairs.map(([, value]) => value as number),
    };
  }
  return null;
}

function mapPlots(run: DisplayTestRun) {
  return Object.entries(run.results)
    .map(([code, value]) => {
      const entries = asMap(value);
      return entries === null ? null : { code, data: mapPlotData(entries) };
    })
    .filter(
      (entry): entry is { code: string; data: MapPlotData } =>
        entry !== null && entry.data !== null,
    );
}

function categoryTick(value: string): string {
  return value.length > 12 ? `${value.slice(0, 10)}…` : value;
}

/** Numeric map values against their discrete keys. Bars make the categorical
 * nature explicit and avoid the point-wave that looked like a degraded copy
 * of the original instrument/array curves. */
function CategoricalMapPlot({ data, valueLabel }: {
  data: MapPlotData;
  valueLabel: string;
}) {
  const width = 320;
  const height = 160;
  const pad = { left: 38, right: 8, top: 10, bottom: 34 };
  const yMin = Math.min(0, ...data.values);
  const yMax = Math.max(0, ...data.values);
  const ySpan = yMax - yMin || 1;
  const plotWidth = width - pad.left - pad.right;
  const xAt = (index: number) =>
    data.values.length === 1
      ? pad.left + plotWidth / 2
      : pad.left + (index / (data.values.length - 1)) * plotWidth;
  const yAt = (value: number) =>
    height - pad.bottom - ((value - yMin) / ySpan) * (height - pad.top - pad.bottom);
  const baseline = yAt(0);
  const barWidth = Math.max(3, Math.min(24, (plotWidth / data.values.length) * 0.64));
  const labelEvery = Math.max(1, Math.ceil(data.keys.length / 6));

  return (
    <figure className="curve">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={t.testResults.categoryPlotAria(valueLabel, data.values.length)}
      >
        <line className="curve-axis" x1={pad.left} y1={baseline} x2={width - pad.right} y2={baseline} />
        <line className="curve-axis" x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} />
        {data.values.map((value, index) => {
          const x = xAt(index);
          const y = yAt(value);
          const barTop = Math.min(y, baseline);
          const barHeight = Math.max(1, Math.abs(baseline - y));
          const showLabel = index === data.keys.length - 1 || index % labelEvery === 0;
          return (
            <g key={data.keys[index]}>
              <rect
                x={x - barWidth / 2}
                y={barTop}
                width={barWidth}
                height={barHeight}
                rx="1.5"
                fill="var(--series)"
              >
                <title>{`${data.keys[index]}: ${formatScalar(value)}`}</title>
              </rect>
              {showLabel && (
                <text className="curve-tick" x={x} y={height - 10} textAnchor="middle">
                  {categoryTick(data.keys[index])}
                </text>
              )}
            </g>
          );
        })}
        <text className="curve-tick" x={pad.left - 4} y={pad.top + 8} textAnchor="end">
          {formatScalar(yMax)}
        </text>
        <text className="curve-tick" x={pad.left - 4} y={height - pad.bottom} textAnchor="end">
          {formatScalar(yMin)}
        </text>
      </svg>
      <figcaption>
        {t.testResults.categoryPlotCaption(valueLabel, data.values.length)}
      </figcaption>
    </figure>
  );
}

function label(run: DisplayTestRun, code: string): string {
  return run.result_meta[code]?.name ?? code;
}

/** Curves first: an IV sweep is the point of the run, the scalars are context. */
export function RunCurves({ run }: { run: DisplayTestRun }) {
  const arrays = Object.entries(run.results)
    .map(([code, value]) => [code, asNumericArray(value)] as const)
    .filter((entry): entry is readonly [string, number[]] => entry[1] !== null);

  const hasDisplayableAttachment = run.attachments.some(
    (attachment) => attachment.stored && isDisplayableImage(attachment),
  );
  // A categorical chart is a fallback, never a replacement for the original
  // numeric-array curve or a locally mirrored instrument image/plot.
  const plots = arrays.length === 0 && !hasDisplayableAttachment ? mapPlots(run) : [];

  if (arrays.length === 0 && plots.length === 0) return null;

  const byCode = new Map(arrays);
  const voltage = byCode.get("VOLTAGE");
  const current = byCode.get("CURRENT");

  if (voltage && current) {
    return (
      <>
        <CurvePlot
          xs={voltage}
          ys={current}
          xLabel={label(run, "VOLTAGE")}
          yLabel={label(run, "CURRENT")}
        />
        {plots.map(({ code, data }) => (
          <CategoricalMapPlot key={code} data={data} valueLabel={label(run, code)} />
        ))}
      </>
    );
  }

  // No known pairing: plot each series against its sample index, which still
  // shows the shape and beats hiding the data behind a raw array dump.
  return (
    <>
      {arrays.map(([code, series]) => (
        <CurvePlot
          key={code}
          xs={series.map((_, index) => index)}
          ys={series}
          xLabel="#"
          yLabel={label(run, code)}
        />
      ))}
      {plots.map(({ code, data }) => (
        <CategoricalMapPlot key={code} data={data} valueLabel={label(run, code)} />
      ))}
    </>
  );
}

/** Every measured value except the curves: scalars, and dict-valued results
 * expanded to their per-position pairs. */
export function RunScalars({ run }: { run: DisplayTestRun }) {
  const scalars = Object.entries(run.results).filter(([, value]) => asNumericArray(value) === null);
  if (scalars.length === 0) return null;

  return (
    <dl className="measure-grid">
      {scalars.map(([code, value]) => {
        const entries = asMap(value);
        return (
          <div className={entries === null ? "measure" : "measure map-measure"} key={code}>
            <dt title={code}>{label(run, code)}</dt>
            {entries === null ? (
              <dd className={value === null || value === undefined ? "muted" : "mono"}>
                {formatScalar(value)}
              </dd>
            ) : (
              <dd>
                <MapValue entries={entries} />
              </dd>
            )}
          </div>
        );
      })}
    </dl>
  );
}

export function RunConditions({ run }: { run: DisplayTestRun }) {
  const entries = Object.entries(run.properties).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  if (entries.length === 0) return null;

  return (
    <details className="conditions">
      <summary>{t.testResults.conditions}</summary>
      <dl className="measure-grid">
        {entries.map(([code, value]) => (
          <div className="measure" key={code}>
            <dt title={code}>{code}</dt>
            <dd className="mono">{formatScalar(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function RunAttachments({ sn, attachments, onOpen }: {
  sn: string;
  attachments: TestRunAttachment[];
  onOpen: (attachment: TestRunAttachment) => void;
}) {
  if (attachments.length === 0) return null;
  const ordered = [...attachments].sort(
    (left, right) =>
      Number(right.stored && isDisplayableImage(right)) -
      Number(left.stored && isDisplayableImage(left)),
  );

  return (
    <div className="img-grid compact">
      {ordered.map((attachment) =>
        attachment.stored && isDisplayableImage(attachment) ? (
          <button
            type="button"
            className="img-thumb"
            key={`${attachment.source}:${attachment.code}`}
            title={attachment.filename ?? attachment.code}
            onClick={() => onOpen(attachment)}
          >
            <img
              src={componentAttachmentUrl(sn, attachment.code, attachment.source)}
              alt={attachment.title ?? attachment.filename ?? t.images.untitled}
              loading="lazy"
            />
          </button>
        ) : (
          <span
            className="img-thumb placeholder"
            key={`${attachment.source}:${attachment.code}`}
            title={attachment.filename ?? attachment.title ?? attachment.test_type ?? attachment.code}
          >
            <span className="img-tag">
              {attachment.stored ? (
                <>
                  <span>
                    {attachment.filename ?? attachment.title ?? attachment.test_type ?? attachment.code}
                  </span>
                  <br />
                  <span>{t.images.storedLocally}</span>
                </>
              ) : t.images.notStored}
            </span>
          </span>
        ),
      )}
    </div>
  );
}

/**
 * The mirrored runs of one component, with staged uploads shown on top.
 *
 * The mirrored runs are always fetched here (`getComponentTests`) rather than
 * handed down from the component preview: they carry the raw measured values —
 * an IV sweep is tens of kilobytes — and this section is mounted lazily, so
 * loading them with the module page would be exactly the traffic the preview
 * payload was slimmed to avoid.
 */
export function TestResultsSection({
  sn,
  refreshKey = 0,
  ghostRuns,
}: {
  sn: string;
  refreshKey?: number;
  /** Staged, not-yet-pushed uploads (`preview.projected.ghost_tests`). They
   * exist nowhere else, so they are merged in rather than fetched. */
  ghostRuns?: ComponentPreviewTest[];
}) {
  const ghosts = ghostRuns;
  const [mirrored, setMirrored] = useState<DisplayTestRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<TestRunAttachment | null>(null);

  function load(signal?: AbortSignal) {
    return getComponentTests(sn, signal)
      .then((data) => {
        setMirrored(data);
        setError(null);
      })
      .catch((err: unknown) => {
        if (signal?.aborted) return;
        setMirrored([]);
        setError(err instanceof ApiError ? err.message : t.testResults.loadError);
      });
  }

  useEffect(() => {
    const ctrl = new AbortController();
    setLightbox(null);
    setMirrored(null);
    void load(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, sn]);

  // Ghosts first: the mirrored list arrives newest-first and a staged upload is
  // newer than anything the PDB has mirrored back yet.
  const runs =
    mirrored === null ? null : ghosts && ghosts.length > 0 ? [...ghosts, ...mirrored] : mirrored;

  return (
    <>
      <h3 className="section-title">{t.testResults.title}</h3>
      <div className="panel">
        {runs === null ? (
          <p className="state-note">{t.common.loading}</p>
        ) : error !== null && runs.length === 0 ? (
          <p className="state-note">{error}</p>
        ) : runs.length === 0 ? (
          <p className="state-note">
            {t.testResults.empty} {t.testResults.hint}
          </p>
        ) : (
          <>
            {/* A failed mirror fetch must not swallow the staged work, which
                lives only in the preview payload. */}
            {error !== null && <p className="state-note">{error}</p>}
            <ul className="run-list">
              {runs.map((run, index) => {
                const ghost = isGhostRun(run);
                return (
                <li
                  className={ghost ? "run ghost-run" : "run"}
                  key={
                    ghost
                      ? `${run.test_type}-ghost-${run.outbox_action_id ?? index}`
                      : `${run.test_type}-${run.external_ref ?? index}`
                  }
                >
                  <div className="run-head">
                    <strong className="run-type">{run.test_type}</strong>
                    <span
                      className={
                        ghost
                          ? "chip amber"
                          : run.passed === true
                            ? "chip green"
                            : run.passed === false
                              ? "chip red"
                              : "chip neutral"
                      }
                    >
                      {ghost
                        ? t.testResults.staged
                        : run.passed === true
                          ? t.testResults.passed
                          : run.passed === false
                            ? t.testResults.failed
                            : t.testResults.pending}
                    </span>
                    {run.run_number !== null && (
                      <span className="chip muted">
                        {t.testResults.runNumber(String(run.run_number))}
                      </span>
                    )}
                    <span className="muted run-date">
                      {ghost && run.measured_at === null
                        ? t.testResults.awaitingSubmission
                        : formatTimestamp(run.measured_at)}
                    </span>
                  </div>
                  <RunAttachments sn={sn} attachments={run.attachments} onOpen={setLightbox} />
                  <RunCurves run={run} />
                  <RunScalars run={run} />
                  {Object.keys(run.results).length === 0 && (
                    <p className="state-note">
                      {ghost ? t.testResults.stagedHint : t.testResults.noValues}
                    </p>
                  )}
                  <RunConditions run={run} />
                </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {lightbox !== null && (
        <ImageLightbox sn={sn} attachment={lightbox} onClose={() => setLightbox(null)} />
      )}
    </>
  );
}
