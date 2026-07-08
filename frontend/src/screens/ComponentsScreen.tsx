import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { NavIntent } from "../App";
import {
  ApiError,
  getComponent,
  getComponents,
  getInstitutes,
  getStageSuggestion,
  postComponentSync,
  postInstitute,
  postOutboxAction,
} from "../api";
import type {
  ComponentDetail,
  ComponentOut,
  Institute,
  RequirementCheck,
  StageSuggestion,
} from "../api";
import { filterDemoComponents, getDemoComponent } from "../demoData";
import { formatTimestamp, t } from "../i18n";
import { roleLabel, stageChipClass } from "../ui";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function sortInstitutes(institutes: Institute[]): Institute[] {
  return [...institutes].sort((a, b) => a.code.localeCompare(b.code));
}

/** Debounce a live-typed value (search-as-you-type without request spam). */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/**
 * Barcode-scanner-first: on Enter, open the exact SN / local-name match, or
 * the single remaining result. Wedge scanners emit the code plus Enter.
 */
function pickScanTarget(rows: ComponentOut[], needle: string): ComponentOut | undefined {
  const upper = needle.toUpperCase();
  const exact = rows.find(
    (r) => r.sn.toUpperCase() === upper || (r.local_name ?? "").toUpperCase() === upper,
  );
  return exact ?? (rows.length === 1 ? rows[0] : undefined);
}

export default function ComponentsScreen({ nav }: { nav?: NavIntent }) {
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("");
  const [rows, setRows] = useState<ComponentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [stageOptions, setStageOptions] = useState<string[]>([]);
  const [selectedSn, setSelectedSn] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [selectedInstitute, setSelectedInstitute] = useState("");
  const [instituteError, setInstituteError] = useState<string | null>(null);
  const [showCreateInstitute, setShowCreateInstitute] = useState(false);
  const [newInstituteCode, setNewInstituteCode] = useState("");
  const [newInstituteName, setNewInstituteName] = useState("");
  const [newInstitutePrefix, setNewInstitutePrefix] = useState("");
  const [creatingInstitute, setCreatingInstitute] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);

  const debouncedQ = useDebounced(q, 250);

  // React to a cross-screen navigation intent (board card click, topbar scan).
  const navToken = nav?.token ?? 0;
  useEffect(() => {
    if (navToken === 0 || nav === undefined) return;
    if (nav.sn !== undefined) {
      setSelectedSn(nav.sn);
    } else if (nav.q !== undefined) {
      setSelectedSn(null);
      setQ(nav.q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navToken]);

  useEffect(() => {
    const ctrl = new AbortController();
    getInstitutes(ctrl.signal)
      .then((data) => {
        const sorted = sortInstitutes(data);
        setInstitutes(sorted);
        setInstituteError(null);
        setSelectedInstitute((current) => {
          if (current !== "" && sorted.some((i) => i.code === current)) return current;
          return sorted[0]?.code ?? "";
        });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) return;
        setInstituteError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    const absorb = (data: ComponentOut[], isDemo: boolean) => {
      setRows(data);
      setDemo(isDemo);
      setLoading(false);
      // Union of every stage seen so far, so options never disappear while filtering.
      setStageOptions((prev) => {
        const next = new Set(prev);
        for (const c of data) next.add(c.stage);
        return [...next].sort();
      });
    };
    getComponents(
      {
        q: debouncedQ || undefined,
        stage: stage || undefined,
        institute: selectedInstitute || undefined,
      },
      ctrl.signal,
    )
      .then((data) => absorb(data, false))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          absorb(filterDemoComponents(debouncedQ, stage, selectedInstitute), true);
        } else {
          setError(errorMessage(err));
          setLoading(false);
        }
      });
    return () => ctrl.abort();
  }, [debouncedQ, stage, selectedInstitute, reloadKey]);

  async function handleScanSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const needle = q.trim();
    if (needle === "") return;
    // Bypass the debounce: scanners send the full code plus Enter within milliseconds.
    try {
      const data = await getComponents({
        q: needle,
        stage: stage || undefined,
        institute: selectedInstitute || undefined,
      });
      const target = pickScanTarget(data, needle);
      if (target !== undefined) setSelectedSn(target.sn);
    } catch (err) {
      if (err instanceof ApiError && err.isNetwork) {
        const target = pickScanTarget(
          filterDemoComponents(needle, stage, selectedInstitute),
          needle,
        );
        if (target !== undefined) setSelectedSn(target.sn);
      }
    }
  }

  async function handleCreateInstitute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = newInstituteCode.trim().toUpperCase();
    const name = newInstituteName.trim();
    const prefix = newInstitutePrefix.trim();
    if (code === "" || name === "") return;

    setCreatingInstitute(true);
    setInstituteError(null);
    setSyncNotice(null);
    try {
      const created = await postInstitute({
        code,
        name,
        local_name_prefix: prefix,
        settings: {},
      });
      setInstitutes((current) =>
        sortInstitutes([...current.filter((i) => i.code !== created.code), created]),
      );
      setSelectedInstitute(created.code);
      setNewInstituteCode("");
      setNewInstituteName("");
      setNewInstitutePrefix("");
      setShowCreateInstitute(false);
      setSyncNotice(t.components.instituteCreated(created.code));
    } catch (err) {
      setInstituteError(errorMessage(err));
    } finally {
      setCreatingInstitute(false);
    }
  }

  async function handleSyncSelectedInstitute() {
    if (selectedInstitute === "") {
      setSyncNotice(t.components.syncNeedsInstitute);
      return;
    }
    setSyncing(true);
    setSyncNotice(null);
    try {
      const result = await postComponentSync(selectedInstitute);
      setSyncNotice(
        t.components.syncComplete(
          result.created,
          result.updated,
          result.unchanged,
          result.skipped,
        ),
      );
      setReloadKey((key) => key + 1);
    } catch (err) {
      setSyncNotice(`${t.components.syncFailed}: ${errorMessage(err)}`);
    } finally {
      setSyncing(false);
    }
  }

  if (selectedSn !== null) {
    return (
      <ComponentDetailPanel
        sn={selectedSn}
        onBack={() => setSelectedSn(null)}
        onOpen={setSelectedSn}
      />
    );
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.components}</h1>
        <span className="sub">{t.components.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>
      {demo && (
        <div className="toolbar">
          <span className="muted">{t.common.demoNote}</span>
        </div>
      )}
      {!demo && (
        <div className="panel compact-panel">
          <div className="toolbar">
            <label className="control-label" htmlFor="institute-filter">
              {t.components.instituteLabel}
            </label>
            <select
              id="institute-filter"
              className="select-input"
              value={selectedInstitute}
              onChange={(e) => setSelectedInstitute(e.target.value)}
            >
              <option value="">{t.components.allInstitutes}</option>
              {institutes.map((institute) => (
                <option key={institute.code} value={institute.code}>
                  {institute.code} - {institute.name}
                </option>
              ))}
            </select>
            <button
              className="btn"
              disabled={syncing || selectedInstitute === ""}
              onClick={() => void handleSyncSelectedInstitute()}
            >
              {syncing ? t.common.loading : t.components.syncSelected}
            </button>
            <button
              className="btn"
              onClick={() => setShowCreateInstitute((visible) => !visible)}
            >
              {showCreateInstitute ? t.common.cancel : t.components.createInstitute}
            </button>
            {institutes.length === 0 && (
              <span className="muted">{t.components.noInstitutes}</span>
            )}
          </div>
          {instituteError !== null && (
            <div className="error-banner" role="alert">
              <span>
                {t.components.loadInstitutesError}: {instituteError}
              </span>
              <button className="btn" onClick={() => setInstituteError(null)}>
                OK
              </button>
            </div>
          )}
          {syncNotice !== null && (
            <div className="info-banner" role="status">
              <span>{syncNotice}</span>
              <button className="btn" onClick={() => setSyncNotice(null)}>
                OK
              </button>
            </div>
          )}
          {showCreateInstitute && (
            <form className="toolbar create-institute-form" onSubmit={handleCreateInstitute}>
              <input
                className="short-input mono"
                value={newInstituteCode}
                onChange={(e) => setNewInstituteCode(e.target.value.toUpperCase())}
                placeholder={t.components.instituteCodePlaceholder}
                aria-label={t.components.instituteCodeLabel}
                maxLength={16}
                required
              />
              <input
                className="text-input"
                value={newInstituteName}
                onChange={(e) => setNewInstituteName(e.target.value)}
                placeholder={t.components.instituteNamePlaceholder}
                aria-label={t.components.instituteNameLabel}
                maxLength={120}
                required
              />
              <input
                className="short-input mono"
                value={newInstitutePrefix}
                onChange={(e) => setNewInstitutePrefix(e.target.value)}
                placeholder={t.components.institutePrefixPlaceholder}
                aria-label={t.components.institutePrefixLabel}
                maxLength={32}
              />
              <button className="btn" disabled={creatingInstitute}>
                {creatingInstitute ? t.common.loading : t.common.create}
              </button>
            </form>
          )}
        </div>
      )}
      <form className="toolbar" role="search" onSubmit={(e) => void handleScanSubmit(e)}>
        <input
          className="search-input"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t.components.searchPlaceholder}
          aria-label={t.components.searchLabel}
          autoFocus
        />
        <select
          className="select-input"
          value={stage}
          onChange={(e) => setStage(e.target.value)}
          aria-label={t.components.stageFilterLabel}
        >
          <option value="">{t.components.allStages}</option>
          {stageOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </form>
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.components.loadError}: {error}
          </span>
          <button className="btn" onClick={() => setReloadKey((k) => k + 1)}>
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : rows.length === 0 ? (
        <p className="state-note">{t.components.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.components.colLocalName}</th>
                <th scope="col">{t.components.colSerial}</th>
                <th scope="col">{t.components.colType}</th>
                <th scope="col">{t.components.colStage}</th>
                <th scope="col">{t.components.colLocation}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.sn}
                  className={c.trashed ? "row-click trashed" : "row-click"}
                  onClick={() => setSelectedSn(c.sn)}
                >
                  <td>
                    <div className="tree-row">
                      <button
                        className="link-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedSn(c.sn);
                        }}
                      >
                        {c.local_name ?? c.sn}
                      </button>
                      {c.is_dummy && <span className="chip muted">{t.components.dummy}</span>}
                      {c.trashed && <span className="chip red">{t.components.trashed}</span>}
                    </div>
                  </td>
                  <td className="mono">{c.sn}</td>
                  <td>{c.component_type}</td>
                  <td>
                    <span className={stageChipClass(c.stage)}>{c.stage}</span>
                  </td>
                  <td>{c.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ComponentDetailPanel({
  sn,
  onBack,
  onOpen,
}: {
  sn: string;
  onBack: () => void;
  onOpen: (sn: string) => void;
}) {
  const [detail, setDetail] = useState<ComponentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [suggestion, setSuggestion] = useState<StageSuggestion | null>(null);

  // Stage suggestion is a best-effort extra: hide the section when the backend
  // is offline or has no data for this component, without disturbing the detail.
  useEffect(() => {
    const ctrl = new AbortController();
    setSuggestion(null);
    getStageSuggestion(sn, ctrl.signal)
      .then((data) => setSuggestion(data))
      .catch(() => {
        /* offline / unknown component: section stays hidden */
      });
    return () => ctrl.abort();
  }, [sn, reloadKey]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setDetail(null);
    getComponent(sn, ctrl.signal)
      .then((data) => {
        setDetail(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          const fallback = getDemoComponent(sn);
          if (fallback !== null) {
            setDetail(fallback);
            setDemo(true);
          } else {
            setError(t.components.notFound);
          }
        } else if (err instanceof ApiError && err.status === 404) {
          setError(t.components.notFound);
        } else {
          setError(errorMessage(err));
        }
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [sn, reloadKey]);

  const toolbar = (
    <div className="toolbar">
      <button className="btn" onClick={onBack}>
        {t.components.backToList}
      </button>
      {demo && <span className="badge warn">{t.common.demoBadge}</span>}
    </div>
  );

  if (error !== null) {
    return (
      <div className="screen">
        {toolbar}
        <div className="error-banner" role="alert">
          <span>
            {t.components.detailLoadError}: {error}
          </span>
          <button className="btn" onClick={() => setReloadKey((k) => k + 1)}>
            {t.common.retry}
          </button>
        </div>
      </div>
    );
  }

  if (loading || detail === null) {
    return (
      <div className="screen">
        {toolbar}
        <p className="state-note">{t.common.loading}</p>
      </div>
    );
  }

  const parentSn = detail.parent_sn;

  return (
    <div className="screen">
      {toolbar}
      <div className="detail-head">
        <h2 className="detail-title">{detail.local_name ?? detail.sn}</h2>
        <span className="mono muted">{detail.sn}</span>
        <span className={stageChipClass(detail.stage)}>{detail.stage}</span>
        {detail.is_dummy && <span className="chip muted">{t.components.dummy}</span>}
        {detail.trashed && <span className="chip red">{t.components.trashed}</span>}
      </div>
      <div className="det">
        <div className="det-col">
          <h3 className="section-title">{t.components.masterData}</h3>
          <div className="panel">
            <div className="field-grid">
              <Field label={t.components.fieldType} value={detail.component_type} />
              <Field label={t.components.fieldTypeCode} value={detail.type_code} mono />
              <Field label={t.components.fieldStage} value={detail.stage} mono />
              <Field label={t.components.fieldLocation} value={detail.location} />
              <Field label={t.components.fieldInstitute} value={detail.institute_code} />
              <Field label={t.components.fieldSynced} value={formatTimestamp(detail.synced_at)} />
            </div>
          </div>
          <h3 className="section-title">{t.components.family}</h3>
          <div className="panel">
            <ul className="tree">
              {parentSn !== null && (
                <li className="tree-row">
                  <span className="role">{t.components.parent}</span>
                  <button className="link-btn mono" onClick={() => onOpen(parentSn)}>
                    {parentSn}
                  </button>
                </li>
              )}
              <li className="tree-row">
                <span className="role">{roleLabel(detail.component_type)}</span>
                <strong>{detail.local_name ?? detail.sn}</strong>
                <span className="mono muted">{detail.sn}</span>
                <span className={stageChipClass(detail.stage)}>{detail.stage}</span>
                <span className="ok is-muted">{t.components.thisComponent}</span>
              </li>
              {detail.children.map((child) => (
                <li className="tree-row lvl1" key={child.sn}>
                  <span className="role">{roleLabel(child.component_type)}</span>
                  <button className="link-btn" onClick={() => onOpen(child.sn)}>
                    {child.local_name ?? child.sn}
                  </button>
                  <span className="mono muted">{child.sn}</span>
                  {child.is_dummy && <span className="chip muted">{t.components.dummy}</span>}
                  {child.trashed ? (
                    <span className="chip red">{t.components.trashed}</span>
                  ) : (
                    <span className="ok">{t.components.assembled} ✓</span>
                  )}
                </li>
              ))}
              {detail.children.length === 0 && (
                <li className="tree-row lvl1">
                  <span className="muted">{t.components.noChildren}</span>
                </li>
              )}
            </ul>
          </div>
        </div>
        <div className="det-col">
          {suggestion !== null ? (
            <StageSuggestionSection
              suggestion={suggestion}
              instituteCode={detail.institute_code}
            />
          ) : (
            <>
              <h3 className="section-title">{t.components.stageTitle}</h3>
              <div className="panel">
                <p className="state-note">{t.components.stageUnavailable}</p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const STATUS_CHIP: Record<RequirementCheck["status"], string> = {
  passed: "chip green",
  failed: "chip red",
  missing: "chip amber",
};

const STATUS_LABEL: Record<RequirementCheck["status"], string> = {
  passed: t.components.stagePassed,
  failed: t.components.stageFailed,
  missing: t.components.stageMissing,
};

function StageSuggestionSection({
  suggestion,
  instituteCode,
}: {
  suggestion: StageSuggestion;
  instituteCode: string;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const [proposing, setProposing] = useState(false);
  const [proposed, setProposed] = useState(false);

  async function handlePropose() {
    if (suggestion.suggested_stage === null) return;
    setProposing(true);
    setNotice(null);
    try {
      const action = await postOutboxAction({
        institute_code: instituteCode,
        kind: "stage_move",
        payload: {
          sn: suggestion.sn,
          from_stage: suggestion.current_stage,
          to_stage: suggestion.suggested_stage,
        },
        created_by: "ui-user",
      });
      setProposed(true);
      setNotice(t.components.stageProposed(action.id, suggestion.suggested_stage));
    } catch (err) {
      setNotice(`${t.components.stageProposeFailed}: ${errorMessage(err)}`);
    } finally {
      setProposing(false);
    }
  }

  return (
    <>
      <h3 className="section-title">{t.components.stageTitle}</h3>
      <div className="panel">
        {suggestion.checks.length === 0 ? (
          <p className="state-note">{t.components.stageNoRequirements}</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.components.stageColTest}</th>
                <th scope="col">{t.components.stageColStage}</th>
                <th scope="col">{t.components.stageColStatus}</th>
              </tr>
            </thead>
            <tbody>
              {suggestion.checks.map((check) => (
                <tr key={`${check.stage}:${check.test_type}`}>
                  <td className="mono">{check.test_type}</td>
                  <td>
                    <span className="chip stage">{check.stage}</span>
                  </td>
                  <td>
                    <span className={STATUS_CHIP[check.status]}>{STATUS_LABEL[check.status]}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className={suggestion.move_suggested ? "callout ok" : "callout"}>
          <span>
            {suggestion.move_suggested && suggestion.suggested_stage !== null
              ? t.components.stageSuggestion(suggestion.suggested_stage)
              : suggestion.next_stage === null
                ? t.components.stageNoNext
                : t.components.stageBlocked}
          </span>
          {suggestion.move_suggested && suggestion.suggested_stage !== null && (
            <button
              className="btn primary"
              disabled={proposing || proposed}
              onClick={() => void handlePropose()}
            >
              {proposing
                ? t.components.stageProposing
                : t.components.stageProposeMove(suggestion.suggested_stage)}
            </button>
          )}
        </div>
        {notice !== null && <p className="state-note">{notice}</p>}
      </div>
    </>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="field-label">{label}</div>
      <div className={mono === true ? "field-value mono" : "field-value"}>{value}</div>
    </div>
  );
}
