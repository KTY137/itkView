import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { NavIntent, ScreenId } from "../App";
import AddTestResult from "../AddTestResult";
import type { RecordTestIntent } from "../AddTestResult";
import ImageLightbox from "../ImageLightbox";
import ModuleWorksheet from "../ModuleWorksheet";
import {
  ApiError,
  componentAttachmentUrl,
  getComponent,
  getComponentAttachments,
  getComponentPreview,
  getComponents,
  getComponentStaged,
  getComponentThumbnails,
  getInstitutes,
  getStageSuggestion,
  getTestTypeSchemas,
  postComponentSyncEvidence,
  postInstitute,
  postOutboxAction,
  postTestTypeSchemaSync,
} from "../api";
import type {
  ChildAttachments,
  ComponentDetail,
  ComponentOut,
  ComponentPreview,
  ComponentPreviewAction,
  ComponentPreviewTest,
  Institute,
  OutboxAction,
  RequirementCheck,
  StageSuggestion,
  TestRunAttachment,
  TestTypeSchema,
} from "../api";
import { TestResultsSection } from "../TestResults";
import { useAuth } from "../auth";
import type {
  ComponentSyncController,
  EvidenceSyncController,
} from "../componentSync";
import { filterDemoComponents, getDemoComponent } from "../demoData";
import { formatTimestamp, t } from "../i18n";
import { SyncProgressPanel } from "../SyncProgress";
import {
  canDiscard,
  canPush,
  discardStagedAction,
  pushToPdb,
} from "../stagedActions";
import {
  readStagedPreviewPreference,
  subscribeStagedPreviewPreference,
} from "../stagedPreview";
import type { StagedPreviewMode } from "../stagedPreview";
import { describeComponent, isDisplayableImage, outboxStatusChipClass, roleLabel, stageChipClass, stageLabel } from "../ui";
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
  evidenceSync,
}: {
  nav?: NavIntent;
  onNavigate?: (screen: ScreenId) => void;
  componentSync: ComponentSyncController;
  evidenceSync: EvidenceSyncController;
}) {
  const { canWrite, isAdmin, user } = useAuth();
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
  const [detailTestType, setDetailTestType] = useState<string | null>(null);
  const [detailIntentToken, setDetailIntentToken] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [selectedInstitute, setSelectedInstitute] = useState("");
  const [instituteError, setInstituteError] = useState<string | null>(null);
  const [showCreateInstitute, setShowCreateInstitute] = useState(false);
  const [newInstituteCode, setNewInstituteCode] = useState("");
  const [newInstituteName, setNewInstituteName] = useState("");
  const [newInstitutePrefix, setNewInstitutePrefix] = useState("");
  const [creatingInstitute, setCreatingInstitute] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  // Serial number -> attachment code for one locally stored image, fetched
  // once for the whole list rather than per row.
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  // If this screen mounts after a job already finished, its initial list fetch
  // already sees the committed snapshot and needs no second request.
  const reloadedSyncJob = useRef<number | null>(
    componentSync.job?.status === "succeeded" ? componentSync.job.id : null,
  );
  const reloadedEvidenceJob = useRef<number | null>(
    evidenceSync.job?.status === "succeeded" ? evidenceSync.job.id : null,
  );

  const debouncedQ = useDebounced(q, 250);
  const canWriteSelectedInstitute =
    canWrite &&
    selectedInstitute !== "" &&
    (user?.institute_code === null || user?.institute_code === selectedInstitute);
  const writableInstitutes =
    user?.institute_code === null
      ? institutes
      : institutes.filter((institute) => institute.code === user?.institute_code);

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

  useEffect(() => {
    const job = evidenceSync.job;
    if (job?.status !== "succeeded" || reloadedEvidenceJob.current === job.id) return;
    reloadedEvidenceJob.current = job.id;
    setReloadKey((key) => key + 1);
  }, [evidenceSync.job]);

  // Rolling readout during an evidence sweep. The sweep commits each component
  // as it arrives, so the mirror already holds the new evidence, thumbnails and
  // attachments while the job is still running — this re-reads it periodically
  // instead of leaving the screen on stale rows until the terminal status.
  // Only the evidence sweep qualifies: the component sync writes its whole
  // mirror in one closing transaction and has nothing to show mid-run.
  useEffect(() => {
    if (evidenceSync.dataEpoch === 0) return;
    setReloadKey((key) => key + 1);
  }, [evidenceSync.dataEpoch]);

  // React to a cross-screen navigation intent (board card click, topbar scan).
  const navToken = nav?.token ?? 0;
  useEffect(() => {
    if (navToken === 0 || nav === undefined) return;
    if (nav.sn !== undefined) {
      setSelectedSn(nav.sn);
      setDetailReturnTo(nav.returnTo ?? null);
      setDetailTestType(nav.testType ?? null);
      setDetailIntentToken(nav.testType === undefined ? 0 : nav.token);
    } else if (nav.q !== undefined) {
      setSelectedSn(null);
      setDetailReturnTo(null);
      setDetailTestType(null);
      setDetailIntentToken(0);
      setQ(nav.q);
    } else {
      // Empty intent (e.g. clicking the "Components" nav while a detail is
      // open): drop the detail and return to the list.
      setSelectedSn(null);
      setDetailReturnTo(null);
      setDetailTestType(null);
      setDetailIntentToken(0);
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
          if (
            user?.institute_code !== null &&
            user?.institute_code !== undefined &&
            sorted.some((institute) => institute.code === user.institute_code)
          ) {
            return user.institute_code;
          }
          return sorted[0]?.code ?? "";
        });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) return;
        setInstituteError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [user?.institute_code]);

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
    setDetailTestType(null);
    setDetailIntentToken(0);
    setSelectedSn(sn);
  }

  function handleDetailBack() {
    const target = detailReturnTo;
    setSelectedSn(null);
    setDetailReturnTo(null);
    setDetailTestType(null);
    setDetailIntentToken(0);
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
    setSyncNotice(null);
    await evidenceSync.start(selectedInstitute);
  }

  if (selectedSn !== null) {
    return (
      <ComponentDetailPanel
        key={selectedSn}
        sn={selectedSn}
        backLabel={
          detailReturnTo === "board" ? t.components.backToBoard : t.components.backToList
        }
        onBack={handleDetailBack}
        onOpen={(sn) => {
          setDetailTestType(null);
          setDetailIntentToken(0);
          setSelectedSn(sn);
        }}
        evidenceJobId={
          evidenceSync.job?.status === "succeeded" ? evidenceSync.job.id : null
        }
        evidenceEpoch={evidenceSync.dataEpoch}
        pinnedTestType={detailTestType}
        testIntentToken={detailIntentToken}
        onNavigate={onNavigate}
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
            {canWriteSelectedInstitute && (
              <>
                <button
                  type="button"
                  className="btn"
                  disabled={
                    componentSync.active ||
                    componentSync.discovering ||
                    evidenceSync.active ||
                    evidenceSync.discovering ||
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
                    evidenceSync.active ||
                    evidenceSync.discovering ||
                    selectedInstitute === ""
                  }
                  onClick={() => void handleSyncInstituteEvidence()}
                >
                  {evidenceSync.discovering
                    ? t.components.checkingEvidenceSync
                    : evidenceSync.active
                    ? t.components.syncingEvidenceInstitute
                    : t.components.syncEvidenceInstitute}
                </button>
              </>
            )}
            {isAdmin && user?.institute_id === null && (
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
          <SyncProgressPanel
            controller={componentSync}
            canRetry={
              canWrite &&
              (user?.institute_code === null ||
                user?.institute_code === componentSync.job?.institute_code)
            }
          />
          <SyncProgressPanel
            controller={evidenceSync}
            canRetry={
              canWrite &&
              (user?.institute_code === null ||
                user?.institute_code === evidenceSync.job?.institute_code)
            }
          />
          {isAdmin && user?.institute_id === null && showCreateInstitute && (
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
          {canWrite && writableInstitutes.length > 0 && (
            <RegisterModuleForm
              institutes={writableInstitutes}
              defaultInstitute={
                writableInstitutes.some((institute) => institute.code === selectedInstitute)
                  ? selectedInstitute
                  : (writableInstitutes[0]?.code ?? "")
              }
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

export function ComponentDetailPanel({
  sn,
  backLabel,
  onBack,
  onOpen,
  evidenceJobId,
  evidenceEpoch,
  pinnedTestType,
  testIntentToken,
  onNavigate,
}: {
  sn: string;
  backLabel: string;
  onBack: () => void;
  onOpen: (sn: string) => void;
  evidenceJobId: number | null;
  /** Rolling readout counter from the evidence sync controller: advances while
   * a sweep is running so an open component does not sit on a stale preview. */
  evidenceEpoch: number;
  pinnedTestType: string | null;
  testIntentToken: number;
  /** Cross-screen navigation (review finding I3: wires the worksheet's "View
   * in Staged" to the same routing the rest of the app already uses). */
  onNavigate?: (screen: ScreenId) => void;
}) {
  const { canWrite, user, showToast } = useAuth();
  const [detail, setDetail] = useState<ComponentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [suggestion, setSuggestion] = useState<StageSuggestion | null>(null);
  const [evidenceSyncing, setEvidenceSyncing] = useState(false);
  const [evidenceNotice, setEvidenceNotice] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<StagedPreviewMode>(() =>
    readStagedPreviewPreference(),
  );
  // Follow the Account-screen preference live: without this the module page
  // kept the mode it was mounted with until a full reload, which read as
  // "the staged tab disappeared".
  useEffect(() => subscribeStagedPreviewPreference(setPreviewMode), []);
  const [preview, setPreview] = useState<ComponentPreview | null>(null);
  const [previewOutbox, setPreviewOutbox] = useState<OutboxAction[]>([]);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<"current" | "staged">("current");
  const [previewReloadKey, setPreviewReloadKey] = useState(0);
  const [testSchemas, setTestSchemas] = useState<TestTypeSchema[]>([]);
  const [testSchemasLoading, setTestSchemasLoading] = useState(false);
  const [testSchemasSyncing, setTestSchemasSyncing] = useState(false);
  const [testSchemasError, setTestSchemasError] = useState<string | null>(null);
  const [testSchemasReloadKey, setTestSchemasReloadKey] = useState(0);
  // Set by a row-level edit-ghost click in the required-tests table below;
  // preselects (but does not lock) the Add-test-result test-type dropdown.
  // `token` must be bumped on every click (see handleRecordTest) — a
  // re-click of the same "missing"/"failed" row carries the same test-type
  // string, which alone would not change React state / re-fire the effect
  // that opens the form a second time (review IMPORTANT #2).
  const [initialTestType, setInitialTestType] = useState<RecordTestIntent | null>(null);
  const recordTestTokenRef = useRef(0);
  // Same intent shape, routed to the worksheet's in-row edit strip instead of
  // AddTestResult whenever the worksheet is the mounted primary view (any
  // preview mode, as long as the preview payload carries a worksheet). See
  // handleRecordTest.
  const [worksheetEditIntent, setWorksheetEditIntent] = useState<RecordTestIntent | null>(null);
  const worksheetEditTokenRef = useRef(0);
  const testSchemaSyncRequest = useRef(0);
  const currentTestSchemaComponentType = useRef<string | null>(null);
  const seenEvidenceJob = useRef<number | null>(evidenceJobId);
  const testSchemaComponentType = detail?.component_type ?? null;
  currentTestSchemaComponentType.current = testSchemaComponentType;
  const canWriteComponent =
    canWrite &&
    detail !== null &&
    (user?.institute_code === null || user?.institute_code === detail.institute_code);

  async function handleSyncEvidence() {
    setEvidenceSyncing(true);
    setEvidenceNotice(null);
    try {
      const result = await postComponentSyncEvidence(sn);
      setEvidenceNotice(
        t.components.syncEvidenceDone(
          result.created,
          result.total,
          result.attachments_downloaded,
          result.attachments_reused,
          result.attachments_failed,
          result.attachments_total,
        ),
      );
      setReloadKey((k) => k + 1); // re-evaluate the stage suggestion with new evidence
      setPreviewReloadKey((key) => key + 1);
    } catch (err) {
      setEvidenceNotice(`${t.components.syncEvidenceFailed}: ${errorMessage(err)}`);
    } finally {
      setEvidenceSyncing(false);
    }
  }

  useEffect(() => {
    if (evidenceJobId === null || seenEvidenceJob.current === evidenceJobId) return;
    seenEvidenceJob.current = evidenceJobId;
    setReloadKey((key) => key + 1);
    setPreviewReloadKey((key) => key + 1);
  }, [evidenceJobId]);

  // Same rolling readout as the list, where it matters more: a person watching
  // one component during a sweep would otherwise read a stale preview — and a
  // stale required-test verdict — for the whole run, even though this
  // component's evidence may already be committed.
  useEffect(() => {
    if (evidenceEpoch === 0) return;
    setReloadKey((key) => key + 1);
    setPreviewReloadKey((key) => key + 1);
  }, [evidenceEpoch]);

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
    setPreviewLoading(true);
    setPreviewError(null);
    Promise.all([
      getComponentPreview(sn, ctrl.signal),
      getComponentStaged(sn, ctrl.signal),
    ])
      .then(([previewData, staged]) => {
        setPreview(previewData);
        setPreviewOutbox(staged);
        setPreviewLoading(false);
      })
      .catch((caught: unknown) => {
        if (ctrl.signal.aborted) return;
        setPreview(null);
        setPreviewOutbox([]);
        setPreviewError(errorMessage(caught));
        setPreviewLoading(false);
      });
    return () => ctrl.abort();
  }, [previewReloadKey, sn]);

  useEffect(() => {
    setPreviewTab("current");
  }, [sn]);

  useEffect(() => {
    if ((preview?.staged_actions.length ?? 0) === 0) setPreviewTab("current");
  }, [preview]);

  useEffect(() => {
    const ctrl = new AbortController();
    setTestSchemas([]);
    setTestSchemasError(null);
    if (testSchemaComponentType === null || demo) {
      setTestSchemasLoading(false);
      return () => ctrl.abort();
    }
    setTestSchemasLoading(true);
    getTestTypeSchemas(testSchemaComponentType, ctrl.signal)
      .then((schemas) => {
        setTestSchemas(schemas);
        setTestSchemasLoading(false);
      })
      .catch((caught: unknown) => {
        if (ctrl.signal.aborted) return;
        setTestSchemasError(errorMessage(caught));
        setTestSchemasLoading(false);
      });
    return () => ctrl.abort();
  }, [demo, testSchemaComponentType, testSchemasReloadKey]);

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

  const stagedCount = preview?.staged_actions.length ?? 0;
  const hasStagedPreview = preview !== null && stagedCount > 0;
  const showingProjection =
    hasStagedPreview &&
    (previewMode === "inline" || (previewMode === "tabs" && previewTab === "staged"));
  const displayedStage = showingProjection ? preview.projected.stage : detail.stage;
  // The worksheet is the primary view whenever preview data is available at
  // all; a stale backend that has not shipped the `worksheet` field yet must
  // fall back to the pre-worksheet sections instead of crashing on it.
  const hasWorksheet = preview !== null && preview.worksheet !== undefined && preview.worksheet !== null;
  // Review finding I7: pass the full mirrored schema rows (test_code/name/id
  // intact) instead of unwrapping to the bare PDB schema JSON — the raw
  // detail's own `code`/`testType` is allowed to be null (the mirror
  // tolerates it), which used to leave the worksheet permanently guessing.
  const worksheetSchemas = testSchemasLoading ? null : testSchemas;

  function refreshPreview() {
    setPreviewReloadKey((key) => key + 1);
  }

  function handleWorksheetStaged(outboxActionId: number) {
    showToast(t.addTest.stagedToast(outboxActionId));
    setReloadKey((key) => key + 1);
    refreshPreview();
  }

  async function handleSyncTestSchemas(componentType: string) {
    const requestId = ++testSchemaSyncRequest.current;
    setTestSchemasSyncing(true);
    setTestSchemasError(null);
    try {
      const result = await postTestTypeSchemaSync(componentType);
      const schemas = await getTestTypeSchemas(componentType);
      if (
        requestId === testSchemaSyncRequest.current &&
        currentTestSchemaComponentType.current === componentType
      ) {
        setTestSchemas(schemas);
        showToast(t.addTest.schemasSynced(result.total));
      }
    } finally {
      if (requestId === testSchemaSyncRequest.current) setTestSchemasSyncing(false);
    }
  }

  function handleRecordTest(testType: string) {
    // Legacy view (preview fetch failed, or a stale backend without the
    // worksheet payload): keep pinning AddTestResult's own test-type dropdown
    // exactly as before. Whenever the worksheet is the mounted primary view —
    // in every preview mode, including "off" — its in-row edit strip owns test
    // entry, so route the intent there instead of scrolling to the form card.
    if (!hasWorksheet) {
      recordTestTokenRef.current += 1;
      setInitialTestType({ testType, token: recordTestTokenRef.current });
      return;
    }
    worksheetEditTokenRef.current += 1;
    setWorksheetEditIntent({ testType, token: worksheetEditTokenRef.current });
  }

  // Spec §H3: the worksheet is the primary test view in all three preview
  // modes (tabs, inline, off), so the same element mounts in every branch.
  const worksheetSection = hasWorksheet ? (
    <ModuleWorksheet
      componentSn={detail.sn}
      componentType={detail.component_type}
      instituteCode={detail.institute_code}
      worksheet={preview.worksheet}
      schemas={worksheetSchemas}
      canWrite={canWriteComponent && !demo}
      refreshKey={reloadKey}
      editIntent={worksheetEditIntent}
      onStaged={handleWorksheetStaged}
      onViewStaged={onNavigate === undefined ? undefined : () => onNavigate("staged")}
    />
  ) : null;

  return (
    <div className="screen">
      {toolbar}
      {previewMode === "tabs" && hasStagedPreview && (
        <div className="preview-tabs" role="group" aria-label={t.components.previewTabsLabel}>
          <button
            type="button"
            className={previewTab === "current" ? "preview-tab active" : "preview-tab"}
            aria-pressed={previewTab === "current"}
            onClick={() => setPreviewTab("current")}
          >
            {t.components.previewCurrent}
          </button>
          <button
            type="button"
            className={previewTab === "staged" ? "preview-tab active" : "preview-tab"}
            aria-pressed={previewTab === "staged"}
            onClick={() => setPreviewTab("staged")}
          >
            {t.components.previewStaged(stagedCount)}
          </button>
        </div>
      )}
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
        {previewMode === "inline" && showingProjection && preview.current.stage !== displayedStage ? (
          <span className="inline-stage-preview" aria-label={t.components.previewStageChange(
            stageLabel(preview.current.stage),
            stageLabel(displayedStage),
          )}>
            <span className={stageChipClass(preview.current.stage)} title={preview.current.stage}>
              {stageLabel(preview.current.stage)}
            </span>
            <span className="preview-arrow" aria-hidden="true">→</span>
            <span className="chip stage ghost-stage" title={displayedStage}>
              {stageLabel(displayedStage)}
            </span>
          </span>
        ) : (
          <span
            className={showingProjection ? "chip stage ghost-stage" : stageChipClass(displayedStage)}
            title={displayedStage}
          >
            {stageLabel(displayedStage)}
          </span>
        )}
        {detail.is_dummy && <span className="chip muted">{t.components.dummy}</span>}
        {detail.trashed && <span className="chip red">{t.components.trashed}</span>}
      </div>
      {previewMode !== "off" && previewLoading && (
        <p className="state-note preview-state-note">{t.components.previewLoading}</p>
      )}
      {previewMode !== "off" && previewError !== null && (
        <div className="info-banner" role="status">
          <span>{t.components.previewLoadError}: {previewError}</span>
          <button type="button" className="btn" onClick={refreshPreview}>{t.common.retry}</button>
        </div>
      )}
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
          {canWriteComponent && (
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
          {canWriteComponent && !demo && (
            <>
              {testSchemasError !== null && (
                <div className="info-banner" role="status">
                  <span>{t.addTest.schemasLoadFailed}: {testSchemasError}</span>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setTestSchemasReloadKey((key) => key + 1)}
                  >
                    {t.common.retry}
                  </button>
                </div>
              )}
              <AddTestResult
                componentSn={detail.sn}
                componentType={detail.component_type}
                instituteCode={detail.institute_code}
                labels={t.addTest}
                schemas={testSchemas}
                schemasLoading={testSchemasLoading}
                schemasSyncing={testSchemasSyncing}
                pinnedTestType={pinnedTestType ?? undefined}
                intentToken={testIntentToken}
                initialTestType={initialTestType ?? undefined}
                onSyncSchemas={handleSyncTestSchemas}
                onRefresh={() => {
                  setReloadKey((key) => key + 1);
                  refreshPreview();
                }}
                onStaged={(action) => showToast(t.addTest.stagedToast(action.id))}
              />
            </>
          )}
          {preview === null ? (
            /* No preview payload (fetch failed / offline demo): the worksheet
             * cannot mount, so the pre-worksheet sections stay exactly as
             * they were, full run list included. */
            <>
              <StagedChangesSection sn={detail.sn} refreshKey={previewReloadKey} />
              {suggestion !== null ? (
                <StageSuggestionSection
                  suggestion={suggestion}
                  instituteCode={detail.institute_code}
                  onStagedChanged={refreshPreview}
                  onRecordTest={handleRecordTest}
                />
              ) : (
                <UnavailableStageSection />
              )}
              <TestResultsSection sn={detail.sn} refreshKey={reloadKey} />
            </>
          ) : showingProjection ? (
            <>
              <StagedActionsPanel
                actions={preview.staged_actions}
                outboxActions={previewOutbox}
                canWrite={canWriteComponent}
                onChanged={refreshPreview}
              />
              {worksheetSection}
              {hasWorksheet ? (
                <>
                  <div className="callout preview-callout">{t.components.previewProjectionHint}</div>
                  <MirroredRunsSection
                    sn={detail.sn}
                    refreshKey={reloadKey}
                    ghostRuns={preview.projected.ghost_tests}
                  />
                </>
              ) : (
                <TestResultsSection
                  sn={detail.sn}
                  refreshKey={reloadKey}
                  ghostRuns={preview.projected.ghost_tests}
                />
              )}
            </>
          ) : (
            /* Current tab, inline without staged actions, and the "off"
             * preference all share this branch; "off" additionally keeps the
             * compact staged-changes list visible (docs/05). */
            <>
              {previewMode === "off" && (
                <StagedChangesSection sn={detail.sn} refreshKey={previewReloadKey} />
              )}
              {suggestion !== null ? (
                <StageSuggestionSection
                  suggestion={suggestion}
                  instituteCode={detail.institute_code}
                  onStagedChanged={refreshPreview}
                  onRecordTest={handleRecordTest}
                />
              ) : (
                <UnavailableStageSection />
              )}
              {worksheetSection}
              {hasWorksheet ? (
                <MirroredRunsSection sn={detail.sn} refreshKey={reloadKey} />
              ) : (
                <TestResultsSection sn={detail.sn} refreshKey={reloadKey} />
              )}
            </>
          )}
          <ImagesSection sn={detail.sn} refreshKey={reloadKey} />
        </div>
      </div>
    </div>
  );
}

/** Spec §H3: the previous full run list is demoted to a collapsed
 * "All mirrored runs" details element below the worksheet — nothing is
 * removed, nothing spams by default. The heavy run payload is only fetched
 * once the element is first opened; after that it stays mounted so closing
 * and reopening does not refetch or lose scroll state. */
function MirroredRunsSection({
  sn,
  refreshKey,
  ghostRuns,
}: {
  sn: string;
  refreshKey: number;
  ghostRuns?: ComponentPreviewTest[];
}) {
  const [everOpened, setEverOpened] = useState(false);
  return (
    <details
      className="panel staged-history run-history"
      onToggle={(event) => {
        if (event.currentTarget.open) setEverOpened(true);
      }}
    >
      <summary>{t.components.mirroredRunsTitle}</summary>
      {everOpened && (
        <TestResultsSection sn={sn} refreshKey={refreshKey} ghostRuns={ghostRuns} />
      )}
    </details>
  );
}

/** Ghost layer: outbox actions staged for this component but not yet pushed to
 * the PDB. Closes the loop with "Propose stage move" — a proposal appears here
 * immediately, rendered as a dashed "ghost" row, until it is confirmed. */
function StagedChangesSection({ sn, refreshKey }: { sn: string; refreshKey: number }) {
  const [staged, setStaged] = useState<OutboxAction[] | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setStaged(null);
    getComponentStaged(sn, ctrl.signal)
      .then(setStaged)
      .catch(() => setStaged([])); // offline / none: show the empty state
    return () => ctrl.abort();
  }, [refreshKey, sn]);

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
                <span className={outboxStatusChipClass(action.status)}>{action.status}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function StagedActionsPanel({
  actions,
  outboxActions,
  canWrite,
  onChanged,
}: {
  actions: ComponentPreviewAction[];
  outboxActions: OutboxAction[];
  canWrite: boolean;
  onChanged: () => void;
}) {
  const { user, showToast } = useAuth();
  const [busy, setBusy] = useState<{ id: number; kind: "push" | "discard" } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function fullAction(id: number): OutboxAction | undefined {
    return outboxActions.find((action) => action.id === id);
  }

  async function handlePush(metadata: ComponentPreviewAction) {
    const action = fullAction(metadata.id);
    if (action === undefined) {
      setNotice(t.components.previewActionUnavailable);
      return;
    }
    setBusy({ id: metadata.id, kind: "push" });
    setNotice(null);
    try {
      await pushToPdb(action, user?.email ?? "ui-user");
      showToast(t.components.previewPushed(metadata.summary));
      onChanged();
    } catch (caught) {
      setNotice(`${t.components.previewPushFailed}: ${errorMessage(caught)}`);
    } finally {
      setBusy(null);
    }
  }

  async function handleDiscard(metadata: ComponentPreviewAction) {
    const action = fullAction(metadata.id);
    if (action === undefined) {
      setNotice(t.components.previewActionUnavailable);
      return;
    }
    setBusy({ id: metadata.id, kind: "discard" });
    setNotice(null);
    try {
      await discardStagedAction(action, user?.email ?? "ui-user");
      showToast(t.components.previewDiscarded(metadata.summary));
      onChanged();
    } catch (caught) {
      setNotice(`${t.components.previewDiscardFailed}: ${errorMessage(caught)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <h3 className="section-title">{t.components.stagedTitle}</h3>
      <div className="panel projected-panel">
        {actions.length === 0 ? (
          <p className="state-note">{t.components.stagedEmpty}</p>
        ) : (
          <ul className="ghost-list staged-action-list" title={t.components.stagedGhostHint}>
            {actions.map((metadata) => {
              const action = fullAction(metadata.id);
              const pushing = busy?.id === metadata.id && busy.kind === "push";
              const discarding = busy?.id === metadata.id && busy.kind === "discard";
              return (
                <li className="ghost-row staged-action-row" key={metadata.id}>
                  <div className="staged-action-main">
                    <span className="chip stage">{metadata.kind}</span>
                    <strong className="ghost-summary">{metadata.summary}</strong>
                    <span className={outboxStatusChipClass(metadata.status)}>
                      {t.components.previewStatuses[metadata.status]}
                    </span>
                  </div>
                  <div className="staged-action-meta">
                    <span>{t.components.previewCreatedBy(metadata.created_by)}</span>
                    <span className="mono muted">{formatTimestamp(metadata.created_at)}</span>
                  </div>
                  {!metadata.submittable && (
                    <p className="staged-scope-hint">
                      {metadata.submittable_reason === "not_dummy"
                        ? t.components.previewDummyOnly
                        : t.components.previewScopeUnavailable}
                    </p>
                  )}
                  {canWrite && (
                    <div className="staged-action-buttons">
                      {metadata.submittable && action !== undefined && canPush(action.status) && (
                        <button
                          type="button"
                          className="btn primary"
                          disabled={busy !== null}
                          onClick={() => void handlePush(metadata)}
                        >
                          {pushing ? t.components.previewPushing : t.components.previewPush}
                        </button>
                      )}
                      {action !== undefined && canDiscard(action.status) && (
                        <button
                          type="button"
                          className="btn"
                          disabled={busy !== null}
                          onClick={() => void handleDiscard(metadata)}
                        >
                          {discarding ? t.components.previewDiscarding : t.components.previewDiscard}
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {notice !== null && <p className="state-note">{notice}</p>}
      </div>
    </>
  );
}


function UnavailableStageSection() {
  return (
    <>
      <h3 className="section-title">{t.components.stageTitle}</h3>
      <div className="panel"><p className="state-note">{t.components.stageUnavailable}</p></div>
    </>
  );
}

function displayableImages(attachments: readonly TestRunAttachment[]): TestRunAttachment[] {
  return attachments.filter((attachment) => attachment.stored && isDisplayableImage(attachment));
}

/** A grid of locally mirrored images, all belonging to the serial `sn`. */
function ImageGrid({
  sn,
  images,
  onOpen,
}: {
  sn: string;
  images: readonly TestRunAttachment[];
  onOpen: (sn: string, image: TestRunAttachment) => void;
}) {
  return (
    <div className="img-grid">
      {images.map((img) => (
        <button
          type="button"
          className="img-thumb"
          key={img.code}
          title={img.title ?? img.filename ?? img.test_type}
          onClick={() => onOpen(sn, img)}
        >
          <img
            src={componentAttachmentUrl(sn, img.code)}
            alt={img.title ?? img.filename ?? t.images.untitled}
          />
          <span className="img-tag">{img.test_type}</span>
        </button>
      ))}
    </div>
  );
}

/** Locally mirrored metrology / visual-inspection images for a component.
 * The detail view never streams from the PDB; evidence sync owns the bytes.
 *
 * The images of the parts built into this component come with it, in one group
 * per child — an operator works on a module while the photographs were taken of
 * its sensors. They are never merged into the component's own grid: whose part
 * is in the picture is part of what the picture says. Each group fetches its
 * bytes under the child's own serial, which is where the mirror filed them. */
function ImagesSection({ sn, refreshKey }: { sn: string; refreshKey: number }) {
  const [images, setImages] = useState<TestRunAttachment[]>([]);
  const [children, setChildren] = useState<ChildAttachments[]>([]);
  const [offline, setOffline] = useState(false);
  const [lightbox, setLightbox] = useState<{ sn: string; attachment: TestRunAttachment } | null>(
    null,
  );

  useEffect(() => {
    const ctrl = new AbortController();
    setImages([]);
    setChildren([]);
    setOffline(false);
    setLightbox(null);
    getComponentAttachments(sn, ctrl.signal)
      .then((family) => {
        setImages(displayableImages(family.attachments));
        setChildren(
          family.children
            .map((child) => ({ ...child, attachments: displayableImages(child.attachments) }))
            .filter((child) => child.attachments.length > 0),
        );
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) setOffline(true);
      });
    return () => ctrl.abort();
  }, [refreshKey, sn]);

  const nothingAnywhere = images.length === 0 && children.length === 0;

  return (
    <>
      <h3 className="section-title">{t.images.title}</h3>
      <div className="panel">
        {offline ? (
          <p className="state-note">{t.images.offlineHint}</p>
        ) : nothingAnywhere ? (
          <p className="state-note">{t.images.empty}</p>
        ) : images.length === 0 ? (
          <p className="state-note">{t.images.ownEmpty}</p>
        ) : (
          <ImageGrid
            sn={sn}
            images={images}
            onOpen={(owner, attachment) => setLightbox({ sn: owner, attachment })}
          />
        )}
      </div>
      {!offline && children.length > 0 && (
        <section className="ws-children">
          <h3 className="section-title">{t.images.childrenTitle}</h3>
          <p className="state-note">{t.images.childrenIntro}</p>
          {children.map((child) => (
            <div className="panel ws-group-panel" key={child.sn}>
              <div className="ws-group-head">
                <span className="chip neutral">
                  {describeComponent({
                    component_type: child.component_type,
                    type_code: child.type_code,
                  })}
                </span>
                <span className="mono">{child.sn}</span>
                {child.local_name !== null && <span className="muted">{child.local_name}</span>}
              </div>
              <ImageGrid
                sn={child.sn}
                images={child.attachments}
                onOpen={(owner, attachment) => setLightbox({ sn: owner, attachment })}
              />
            </div>
          ))}
        </section>
      )}
      {lightbox !== null && (
        <ImageLightbox
          sn={lightbox.sn}
          attachment={lightbox.attachment}
          onClose={() => setLightbox(null)}
        />
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

export function StageSuggestionSection({
  suggestion,
  instituteCode,
  onStagedChanged,
  onRecordTest,
}: {
  suggestion: StageSuggestion;
  instituteCode: string;
  onStagedChanged: () => void;
  onRecordTest?: (testType: string) => void;
}) {
  const { canWrite, user } = useAuth();
  const canWriteInstitute =
    canWrite &&
    (user?.institute_code === null || user?.institute_code === instituteCode);
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
      onStagedChanged();
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
              {suggestion.checks.map((check) => {
                const editable =
                  canWriteInstitute &&
                  onRecordTest !== undefined &&
                  (check.status === "missing" || check.status === "failed");
                return (
                  <tr
                    className={editable ? "req-row-editable" : undefined}
                    key={`${check.stage}:${check.test_type}`}
                  >
                    <td className="mono">{check.test_type}</td>
                    <td>
                      <span className={stageChipClass(check.stage)} title={check.stage}>
                        {stageLabel(check.stage)}
                      </span>
                    </td>
                    <td>
                      <span className="req-status-cell">
                        <span className={STATUS_CHIP[check.status]}>{STATUS_LABEL[check.status]}</span>
                        {editable && (
                          <button
                            type="button"
                            className="req-edit-ghost"
                            title={t.components.recordTestFor(check.test_type)}
                            aria-label={t.components.recordTestFor(check.test_type)}
                            onClick={() => onRecordTest?.(check.test_type)}
                          >
                            <span aria-hidden="true" className="req-edit-ghost-glyph">✎</span>
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
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
          {canWriteInstitute &&
            suggestion.move_suggested &&
            suggestion.suggested_stage !== null && (
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
