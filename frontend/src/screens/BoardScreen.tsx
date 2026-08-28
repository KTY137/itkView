import { useEffect, useState } from "react";
import { ApiError, getComponents } from "../api";
import type { ComponentOut } from "../api";
import { filterDemoComponents } from "../demoData";
import { t } from "../i18n";
import {
  ProductionStatusMarker,
  hasProductionStatusAttention,
} from "../ProductionStatusMarker";
import { describeComponent, stageLabel, stageTone } from "../ui";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// Canonical production stage order (mirrors the backend seed stage model).
// Any stage a component reports that is not listed here is appended, so the
// board never hides work — new stages simply show up at the end.
const STAGE_ORDER = [
  "HV_TAB_ATTACHED",
  "GLUED",
  "STITCH_BONDING",
  "BONDED",
  "TESTED",
  "FINISHED",
];

function orderedStages(present: Set<string>): string[] {
  const known = STAGE_ORDER.filter((s) => present.has(s));
  const extra = [...present].filter((s) => !STAGE_ORDER.includes(s)).sort();
  return [...known, ...extra];
}

/** The assembly board shows modules (the assembly units), grouped by stage. */
export default function BoardScreen({
  onOpen,
  onAssemble,
}: {
  onOpen: (sn: string) => void;
  onAssemble: () => void;
}) {
  const [modules, setModules] = useState<ComponentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    const keepModules = (rows: ComponentOut[]) => rows.filter((c) => c.component_type === "MODULE");
    getComponents({ component_type: "MODULE" }, ctrl.signal)
      .then((rows) => {
        setModules(rows);
        setDemo(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setModules(keepModules(filterDemoComponents("", "")));
          setDemo(true);
        } else {
          setError(errorMessage(err));
        }
        setLoading(false);
      });
    return () => ctrl.abort();
  }, []);

  const present = new Set(modules.map((m) => m.stage));
  const stages = orderedStages(present);
  const byStage = (stage: string) =>
    modules
      .filter((m) => m.stage === stage)
      .sort((a, b) => {
        const rank = (component: ComponentOut) =>
          component.production_status === "hold"
            ? 0
            : component.production_status === "unknown" &&
                hasProductionStatusAttention(component)
              ? 1
              : 2;
        return rank(a) - rank(b);
      });

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.board}</h1>
        <span className="sub">{t.board.subtitle(modules.length)}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
        <button type="button" className="btn primary cta" onClick={onAssemble}>
          {t.assembly.start}
        </button>
      </div>
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.board.loadError}: {error}
          </span>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : modules.length === 0 ? (
        <p className="state-note">{t.board.empty}</p>
      ) : (
        <div className="board-wrap">
          <div className="board">
            {stages.map((stage) => (
              <div className="col" key={stage}>
                <div className="col-h" data-tone={stageTone(stage)}>
                  <span className="stg-wrap">
                    <span className="stg">{stageLabel(stage)}</span>
                    <span className="stg-code">{stage}</span>
                  </span>
                  <span className="n">{byStage(stage).length}</span>
                </div>
                <div className="col-list">
                  {byStage(stage).map((m) => {
                    const movedAway = m.location !== "" && m.location !== m.institute_code;
                    const hasFlags = m.is_dummy || m.stale || m.trashed || movedAway;
                    const productionTone =
                      m.production_status === "hold"
                        ? "crit"
                        : m.production_status === "unknown" && hasProductionStatusAttention(m)
                          ? "warn"
                          : stageTone(stage);
                    return (
                      <button
                        type="button"
                        className={
                          "card" +
                          (m.trashed ? " trashed" : "") +
                          (m.stale ? " is-stale" : "") +
                          (m.production_status === "hold" ? " has-production-hold" : "")
                        }
                        data-tone={m.trashed ? "crit" : productionTone}
                        key={m.sn}
                        onClick={() => onOpen(m.sn)}
                      >
                        <div className="nm">
                          <span className="nm-label" title={m.local_name ?? m.sn}>
                            {m.local_name ?? m.sn}
                          </span>
                          <ProductionStatusMarker component={m} mode="icon" />
                          <span className="typ" title={describeComponent(m)}>
                            {m.type_code}
                          </span>
                        </div>
                        <div className="sn">{m.sn}</div>
                        {hasFlags && (
                          <div className="row">
                            {movedAway && (
                              <span className="chip neutral" title={t.board.locationHint}>
                                @{m.location}
                              </span>
                            )}
                            {m.is_dummy && <span className="chip muted">{t.board.dummy}</span>}
                            {m.stale && (
                              <span className="chip stale" title={t.components.staleHint}>
                                {t.board.stale}
                              </span>
                            )}
                            {m.trashed && <span className="chip red">{t.board.trashed}</span>}
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
