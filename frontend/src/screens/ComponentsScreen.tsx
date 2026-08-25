import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { NavIntent, ScreenId } from "../App";
import {
  ApiError,
  componentAttachmentUrl,
  componentImageUrl,
  getComponent,
  getComponentImages,
  getComponents,
  getComponentStaged,
  getComponentThumbnails,
  getInstitutes,
  getStageSuggestion,
  postComponentSyncEvidence,
  postInstitute,
  postInstituteEvidenceSync,
  postOutboxAction,
} from "../api";
import type {
  ComponentDetail,
  ComponentImage,
  ComponentOut,
  Institute,
  OutboxAction,
  RequirementCheck,
  StageSuggestion,
} from "../api";
import { TestResultsSection } from "../TestResults";
import { useAuth } from "../auth";
import type { ComponentSyncController } from "../componentSync";
import { filterDemoComponents, getDemoComponent } from "../demoData";
import { formatTimestamp, t } from "../i18n";
import { SyncProgressPanel } from "../SyncProgress";
import { describeComponent, roleLabel, stageChipClass, stageLabel } from "../ui";
import RegisterModuleForm from "./RegisterModuleForm";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Client-side sort for the component list. "default" keeps the server order
 * (local name first, then serial number). */
function sortRows(rows: ComponentOut[], sortBy: string): ComponentOut[] {
  const sorted = [...rows];
  const bySn = (a: ComponentOut, b: ComponentOut) => a.sn.localeCompare(b.sn);
  switch (sortBy) {
    case "serial":
      sorted.sort(bySn);
      break;
    case "stage":
      sorted.sort((a, b) => a.stage.localeCompare(b.stage) || bySn(a, b));
      break;
    case "type":
      sorted.sort((a, b) => a.component_type.localeCompare(b.component_type) || bySn(a, b));
      break;
    default:
      break;
  }
  return sorted;
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

export default function ComponentsScreen({
  nav,
  onNavigate,
  componentSync,
}: {
  nav?: NavIntent;
  onNavigate?: (screen: ScreenId) => void;
  componentSync: ComponentSyncController;
}) {
  const { canWrite, isAdmin } = useAuth();
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("");
  const [rows, setRows] = useState<ComponentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [stageOptions, setStageOptions] = useState<string[]>([]);
  const [componentType, setComponentType] = useState("");
  const [typeOptions, setTypeOptions] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState("default");
  const [staleFilter, setStaleFilter] = useState("all");
  const [selectedSn, setSelectedSn] = useState<string | null>(null);
  const [detailReturnTo, setDetailReturnTo] = useState<ScreenId | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [selectedInstitute, setSelectedInstitute] = useState("");
  const [instituteError, setInstituteError] = useState<string | null>(null);
  const [showCreateInstitute, setShowCreateInstitute] = useState(false);
  const [newInstituteCode, setNewInstituteCode] = useState("");
  const [newInstituteName, setNewInstituteName] = useState("");
  const [newInstitutePrefix, setNewInstitutePrefix] = useState("");
  const [creatingInstitute, setCreatingInstitute] = useState(false);
  const [evidenceSyncing, setEvidenceSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  // Serial number -> attachment code for one locally stored image, fetched
  // once for the whole list rather than per row.
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  // If this screen mounts after a job already finished, its initial list fetch
  // already sees the committed snapshot and needs no second request.
  const reloadedSyncJob = useRef<number | null>(
    componentSync.job?.status === "succeeded" ? componentSync.job.id : null,
  );

  const debouncedQ = useDebounced(q, 250);

  // Refresh the heavy component list once, only after the background job has
  // committed. Progress polling itself only reads the tiny job-status record.
  // Thumbnails are a nicety: a failure here must leave the list untouched.
  useEffect(() => {
    const ctrl = new AbortController();
    getComponentThumbnails(selectedInstitute || undefined, ctrl.signal)
      .then(setThumbnails)
      .catch(() => setThumbnails({}));
    return () => ctrl.abort();
  }, [selectedInstitute, reloadKey]);

  useEffect(() => {
    const job = componentSync.job;
    if (job?.status !== "succeeded" || reloadedSyncJob.current === job.id) return;
    reloadedSyncJob.current = job.id;
    setReloadKey((key) => key + 1);
  }, [componentSync.job]);

  // React to a cross-screen navigation intent (board card click, topbar scan).
  const navToken = nav?.token ?? 0;
  useEffect(() => {
    if (navToken === 0 || nav === undefined) return;
    if (nav.sn !== undefined) {
      setSelectedSn(nav.sn);
      setDetailReturnTo(nav.returnTo ?? null);
    } else if (nav.q !== undefined) {
      setSelectedSn(null);
      setDetailReturnTo(null);
      setQ(nav.q);
    } else {
      // Empty intent (e.g. clicking the "Components" nav while a detail is
      // open): drop the detail and return to the list.
      setSelectedSn(null);
      setDetailReturnTo(null);
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
      // Union of every stage/type seen so far, so options never disappear.
      setStageOptions((prev) => {
        const next = new Set(prev);
        for (const c of data) next.add(c.stage);
        return [...next].sort();
      });
      setTypeOptions((prev) => {
        const next = new Set(prev);
        for (const c of data) next.add(c.component_type);
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
      if (target !== undefined) openFromList(target.sn);
    } catch (err) {
      if (err instanceof ApiError && err.isNetwork) {
        const target = pickScanTarget(
          filterDemoComponents(needle, stage, selectedInstitute),
          needle,
        );
        if (target !== undefined) openFromList(target.sn);
      }
    }
  }

  function openFromList(sn: string) {
    setDetailReturnTo(null);
    setSelectedSn(sn);
  }

  function handleDetailBack() {
    const target = detailReturnTo;
    setSelectedSn(null);
    setDetailReturnTo(null);
    if (target !== null && target !== "components" && onNavigate !== undefined) {
      onNavigate(target);
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
    setSyncNotice(null);
    await componentSync.start(selectedInstitute);
  }

  async function handleSyncInstituteEvidence() {
    if (selectedInstitute === "") {
      setSyncNotice(t.components.syncNeedsInstitute);
      return;
    }
    setEvidenceSyncing(true);
    setSyncNotice(null);
    try {
      const result = await postInstituteEvidenceSync(selectedInstitute);
      setSyncNotice(
        t.components.syncEvidenceInstituteDone(result.created, result.components_processed),
      );
    } catch (err) {
      setSyncNotice(`${t.components.syncFailed}: ${errorMessage(err)}`);
    } finally {
      setEvidenceSyncing(false);
    }
  }

  if (selectedSn !== null) {
    return (
      <ComponentDetailPanel
        sn={selectedSn}
        backLabel={
          detailReturnTo === "board" ? t.components.backToBoard : t.components.backToList
        }
        onBack={handleDetailBack}
        onOpen={setSelectedSn}
      />
    );
  }

  const displayRows = sortRows(
    rows
      .filter((r) => componentType === "" || r.component_type === componentType)
      .filter((r) =>
        staleFilter === "all" ? true : staleFilter === "only" ? r.stale : !r.stale,
      ),
    sortBy,
  );

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
            {canWrite && (
              <>
                <button
                  type="button"
                  className="btn"
                  disabled={
                    componentSync.active ||
                    componentSync.discovering ||
                    evidenceSyncing ||
                    selectedInstitute === ""
                  }
                  onClick={() => void handleSyncSelectedInstitute()}
                >
                  {componentSync.discovering
                    ? t.components.checkingSync
                    : componentSync.active
                      ? t.components.syncingComponents
                      : t.components.syncSelected}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={
                    componentSync.active ||
                    componentSync.discovering ||
                    evidenceSyncing ||
                    selectedInstitute === ""
                  }
                  onClick={() => void handleSyncInstituteEvidence()}
                >
                  {evidenceSyncing
                    ? t.components.syncingEvidenceInstitute
                    : t.components.syncEvidenceInstitute}
                </button>
              </>
            )}
            {isAdmin && (
              <button
                type="button"
                className="btn"
                onClick={() => setShowCreateInstitute((visible) => !visible)}
              >
                {showCreateInstitute ? t.common.cancel : t.components.createInstitute}
              </button>
            )}
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
          <SyncProgressPanel controller={componentSync} canRetry={canWrite} />
          {isAdmin && showCreateInstitute && (
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
          {canWrite && (
            <RegisterModuleForm
              institutes={institutes}
              defaultInstitute={selectedInstitute}
              onDone={(message) => setSyncNotice(message)}
            />
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
              {stageLabel(s)}
            </option>
          ))}
        </select>
        <select
          className="select-input"
          value={componentType}
          onChange={(e) => setComponentType(e.target.value)}
          aria-label={t.components.typeFilterLabel}
        >
          <option value="">{t.components.allTypes}</option>
          {typeOptions.map((tp) => (
            <option key={tp} value={tp}>
              {roleLabel(tp)}
            </option>
          ))}
        </select>
        <select
          className="select-input"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          aria-label={t.components.sortByLabel}
        >
          <option value="default">{t.components.sortDefault}</option>
          <option value="serial">{t.components.sortSerial}</option>
          <option value="stage">{t.components.sortStage}</option>
          <option value="type">{t.components.sortType}</option>
        </select>
        <select
          className="select-input"
          value={staleFilter}
          onChange={(e) => setStaleFilter(e.target.value)}
          aria-label={t.components.staleFilterLabel}
        >
          <option value="all">{t.components.staleAll}</option>
          <option value="hide">{t.components.staleHide}</option>
          <option value="only">{t.components.staleOnly}</option>
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
      ) : displayRows.length === 0 ? (
        <p className="state-note">{t.components.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col" className="col-thumb">
                  <span className="sr-only">{t.images.title}</span>
                </th>
                <th scope="col">{t.components.colLocalName}</th>
                <th scope="col">{t.components.colSerial}</th>
                <th scope="col">{t.components.colType}</th>
                <th scope="col">{t.components.colStage}</th>
                <th scope="col">{t.components.colLocation}</th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map((c) => (
                <tr
                  key={c.sn}
                  className={
                    "row-click" + (c.trashed ? " trashed" : "") + (c.stale ? " is-stale" : "")
                  }
                  onClick={() => openFromList(c.sn)}
                >
                  <td className="col-thumb">
                    {thumbnails[c.sn] !== undefined && (
                      <img
                        className="row-thumb"
                        src={componentAttachmentUrl(c.sn, thumbnails[c.sn])}
                        alt=""
                        loading="lazy"
                      />
                    )}
                  </td>
                  <td>
                    <div className="tree-row">
                      <button
                        className="link-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          openFromList(c.sn);
                        }}
                      >
                        {c.local_name ?? c.sn}
                      </button>
                      {c.is_dummy && <span className="chip muted">{t.components.dummy}</span>}
                      {c.stale && (
                        <span className="chip stale" title={t.components.staleHint}>
                          {t.components.stale}
                        </span>
                      )}
                      {c.trashed && <span className="chip red">{t.components.trashed}</span>}
                    </div>
                  </td>
                  <td className="mono">{c.sn}</td>
                  <td title={c.type_code}>{describeComponent(c)}</td>
                  <td>
                    <span className={stageChipClass(c.stage)} title={c.stage}>
                      {stageLabel(c.stage)}
                    </span>
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
  backLabel,
  onBack,
  onOpen,
}: {
  sn: string;
  backLabel: string;
  onBack: () => void;
  onOpen: (sn: string) => void;
}) {
  const { canWrite, showToast } = useAuth();
  const [detail, setDetail] = useState<ComponentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [suggestion, setSuggestion] = useState<StageSuggestion | null>(null);
  const [evidenceSyncing, setEvidenceSyncing] = useState(false);
  const [evidenceNotice, setEvidenceNotice] = useState<string | null>(null);

  async function handleSyncEvidence() {
    setEvidenceSyncing(true);
    setEvidenceNotice(null);
    try {
      const result = await postComponentSyncEvidence(sn);
      setEvidenceNotice(t.components.syncEvidenceDone(result.created, result.total));
      setReloadKey((k) => k + 1); // re-evaluate the stage suggestion with new evidence
    } catch (err) {
      setEvidenceNotice(`${t.components.syncEvidenceFailed}: ${errorMessage(err)}`);
    } finally {
      setEvidenceSyncing(false);
    }
  }

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
        {backLabel}
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

  const copySn = (sn: string) => {
    if (!navigator.clipboard) {
      showToast(t.components.snCopyFailed);
      return;
    }
    void navigator.clipboard
      .writeText(sn)
      .then(() => showToast(t.components.snCopied(sn)))
      .catch(() => showToast(t.components.snCopyFailed));
  };

  return (
    <div className="screen">
      {toolbar}
      <div className="detail-head">
        <h2 className="detail-title">{detail.local_name ?? detail.sn}</h2>
        <button
          type="button"
          className="sn-copy mono muted"
          onClick={() => copySn(detail.sn)}
          title={t.components.copySn}
          aria-label={t.components.copySn}
        >
          {detail.sn}
          <span className="sn-copy-ic" aria-hidden="true">
            ⧉
          </span>
        </button>
        <span className={stageChipClass(detail.stage)} title={detail.stage}>
          {stageLabel(detail.stage)}
        </span>
        {detail.is_dummy && <span className="chip muted">{t.components.dummy}</span>}
        {detail.trashed && <span className="chip red">{t.components.trashed}</span>}
      </div>
      <div className="det">
        <div className="det-col">
          <h3 className="section-title">{t.components.masterData}</h3>
          <div className="panel">
            <div className="field-grid">
              <Field label={t.components.fieldType} value={describeComponent(detail)} />
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
                <span className={stageChipClass(detail.stage)} title={detail.stage}>
                  {stageLabel(detail.stage)}
                </span>
                <span className="ok is-muted">{t.components.thisComponent}</span>
              </li>
              {detail.children.map((child) => (
                <li className="tree-row lvl1" key={child.sn}>
                  <span className="role" title={describeComponent(child)}>
                    {roleLabel(child.component_type)}
                  </span>
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
          {canWrite && (
            <>
              <div className="toolbar">
                <button
                  type="button"
                  className="btn"
                  disabled={evidenceSyncing}
                  onClick={() => void handleSyncEvidence()}
                >
                  {evidenceSyncing ? t.components.syncingEvidence : t.components.syncEvidence}
                </button>
              </div>
              {evidenceNotice !== null && (
                <div className="info-banner" role="status">
                  <span>{evidenceNotice}</span>
                  <button type="button" className="btn" onClick={() => setEvidenceNotice(null)}>
                    OK
                  </button>
                </div>
              )}
            </>
          )}
          <StagedChangesSection sn={detail.sn} />
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
          <TestResultsSection sn={detail.sn} canWrite={canWrite} />
          <ImagesSection sn={detail.sn} />
        </div>
      </div>
    </div>
  );
}

/** Ghost layer: outbox actions staged for this component but not yet pushed to
 * the PDB. Closes the loop with "Propose stage move" — a proposal appears here
 * immediately, rendered as a dashed "ghost" row, until it is confirmed. */
function StagedChangesSection({ sn }: { sn: string }) {
  const [staged, setStaged] = useState<OutboxAction[] | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setStaged(null);
    getComponentStaged(sn, ctrl.signal)
      .then(setStaged)
      .catch(() => setStaged([])); // offline / none: show the empty state
    return () => ctrl.abort();
  }, [sn]);

  function summarize(action: OutboxAction): string {
    const p = action.payload ?? {};
    if (action.kind === "stage_move" && typeof p.to_stage === "string") {
      return t.components.stagedTo(p.to_stage);
    }
    if (action.kind === "upload_test_run" && typeof p.test_type === "string") {
      return p.test_type;
    }
    return action.kind;
  }

  return (
    <>
      <h3 className="section-title">{t.components.stagedTitle}</h3>
      <div className="panel">
        {staged === null ? (
          <p className="state-note">{t.common.loading}</p>
        ) : staged.length === 0 ? (
          <p className="state-note">{t.components.stagedEmpty}</p>
        ) : (
          <ul className="ghost-list" title={t.components.stagedGhostHint}>
            {staged.map((action) => (
              <li className="ghost-row" key={action.id}>
                <span className="chip stage">{action.kind}</span>
                <span className="ghost-summary">{summarize(action)}</span>
                <span className={statusChip(action.status)}>{action.status}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function statusChip(status: string): string {
  if (status === "confirmed") return "chip green";
  if (status === "failed") return "chip red";
  if (status === "cancelled") return "chip muted";
  return "chip amber"; // draft / validated / approved / submitted are in-flight
}

/** Metrology / visual-inspection images for a component, pulled from the PDB.
 * Best-effort: shows a thumbnail grid with a click-to-enlarge lightbox, an
 * empty state, and a gentle offline hint when the backend is not reachable. */
function ImagesSection({ sn }: { sn: string }) {
  const [images, setImages] = useState<ComponentImage[]>([]);
  const [offline, setOffline] = useState(false);
  const [lightbox, setLightbox] = useState<ComponentImage | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setImages([]);
    setOffline(false);
    setLightbox(null);
    getComponentImages(sn, ctrl.signal)
      .then(setImages)
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) setOffline(true);
      });
    return () => ctrl.abort();
  }, [sn]);

  return (
    <>
      <h3 className="section-title">{t.images.title}</h3>
      <div className="panel">
        {offline ? (
          <p className="state-note">{t.images.offlineHint}</p>
        ) : images.length === 0 ? (
          <p className="state-note">{t.images.empty}</p>
        ) : (
          <div className="img-grid">
            {images.map((img) => (
              <button
                type="button"
                className="img-thumb"
                key={img.id}
                title={img.test_type ?? img.title}
                onClick={() => setLightbox(img)}
              >
                <img
                  src={componentImageUrl(sn, img.id, img.test_run_ref)}
                  alt={img.title || t.images.untitled}
                />
                {img.test_type !== null && <span className="img-tag">{img.test_type}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      {lightbox !== null && (
        <div className="img-lightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          <button type="button" className="img-lightbox-close" aria-label={t.images.close}>
            ×
          </button>
          <img
            src={componentImageUrl(sn, lightbox.id, lightbox.test_run_ref)}
            alt={lightbox.title || t.images.untitled}
          />
          <div className="img-lightbox-cap">
            {lightbox.test_type ? `${lightbox.test_type} · ` : ""}
            {lightbox.filename ?? lightbox.title}
          </div>
        </div>
      )}
    </>
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
  const { canWrite, user } = useAuth();
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
        created_by: user?.email ?? "ui-user",
      });
      setProposed(true);
      setNotice(t.components.stageProposed(action.id, stageLabel(suggestion.suggested_stage)));
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
                    <span className={stageChipClass(check.stage)} title={check.stage}>
                      {stageLabel(check.stage)}
                    </span>
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
              ? t.components.stageSuggestion(stageLabel(suggestion.suggested_stage))
              : suggestion.next_stage === null
                ? t.components.stageNoNext
                : t.components.stageBlocked}
          </span>
          {canWrite && suggestion.move_suggested && suggestion.suggested_stage !== null && (
            <button
              className="btn primary"
              type="button"
              disabled={proposing || proposed}
              onClick={() => void handlePropose()}
            >
              {proposing
                ? t.components.stageProposing
                : t.components.stageProposeMove(stageLabel(suggestion.suggested_stage))}
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
