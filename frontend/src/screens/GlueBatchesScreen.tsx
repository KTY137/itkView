import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ApiError,
  getGlueBatches,
  getGlueUsage,
  patchGlueBatch,
  postGlueBatch,
  postGlueBatchMix,
  postGlueUsage,
  scanGlueBatch,
} from "../api";
import type { GlueBatch, GlueBatchStatus, GlueUsage } from "../api";
import { useAuth } from "../auth";
import { filterDemoGlueBatches, makeDemoGlueBatches, makeDemoGlueUsage } from "../demoData";
import { formatDuration, formatRelative, formatTimestamp, parseApiTimestamp, t } from "../i18n";

const STATUSES: GlueBatchStatus[] = ["new", "in_use", "expired", "empty"];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusLabel(status: GlueBatchStatus): string {
  if (status === "new") return t.glue.statusNew;
  if (status === "in_use") return t.glue.statusInUse;
  if (status === "expired") return t.glue.statusExpired;
  return t.glue.statusEmpty;
}

function statusChip(status: GlueBatchStatus): string {
  if (status === "in_use") return "chip green";
  if (status === "expired") return "chip red";
  if (status === "empty") return "chip muted";
  return "chip neutral";
}

type PotLifeState =
  | { kind: "not_mixed" }
  | { kind: "untimed" }
  | { kind: "running"; seconds: number }
  | { kind: "expired" };

/** Client-side pot-life countdown: the server snapshot only anchors it, the
 * live value ticks from mixed_at + pot_life_minutes against the shared clock. */
function potLifeState(batch: GlueBatch, nowMs: number): PotLifeState {
  if (batch.mixed_at === null) return { kind: "not_mixed" };
  if (batch.pot_life_minutes === null || batch.pot_life_remaining_seconds === null) {
    return { kind: "untimed" };
  }
  const mixedMs = parseApiTimestamp(batch.mixed_at).getTime();
  const seconds = Number.isNaN(mixedMs)
    ? batch.pot_life_remaining_seconds
    : Math.floor((mixedMs + batch.pot_life_minutes * 60_000 - nowMs) / 1_000);
  if (seconds <= 0) return { kind: "expired" };
  return { kind: "running", seconds };
}

function potLifeText(batch: GlueBatch, nowMs: number): string {
  const state = potLifeState(batch, nowMs);
  if (state.kind === "not_mixed") return t.glue.potLifeNotMixed;
  if (state.kind === "untimed") return t.glue.potLifeUntimed;
  if (state.kind === "expired") return t.glue.potLifeExpired;
  return formatDuration(state.seconds);
}

function PotLifeCell({ batch, nowMs }: { batch: GlueBatch; nowMs: number }) {
  const state = potLifeState(batch, nowMs);
  if (state.kind === "not_mixed") return <span className="muted">{t.glue.potLifeNotMixed}</span>;
  if (state.kind === "untimed") return <span className="chip neutral">{t.glue.potLifeUntimed}</span>;
  if (state.kind === "expired") return <span className="chip red">{t.glue.potLifeExpired}</span>;
  return <span className="chip green">{formatDuration(state.seconds)}</span>;
}

/** Offline scan resolution: batch number or PDB serial, case-insensitive. */
function scanDemoGlueBatch(code: string): GlueBatch | undefined {
  const needle = code.toLowerCase();
  return makeDemoGlueBatches().find(
    (batch) =>
      batch.batch_no.toLowerCase() === needle ||
      (batch.pdb_sn !== null && batch.pdb_sn.toLowerCase() === needle),
  );
}

/** A date-only input becomes a full ISO timestamp for the API. */
function optionalIsoDate(value: string): string | undefined {
  return value === "" ? undefined : `${value}T00:00:00.000Z`;
}

/**
 * Phase-4 glue registry: scanner-first lookup, batch lifecycle (mix / empty /
 * expired), a live pot-life countdown and an auditable per-component usage log.
 * The scan input doubles as the free-text filter — Enter resolves it as a scan
 * (the prepared i18n strings only carry one search/scan placeholder).
 */
export default function GlueBatchesScreen() {
  const { canWrite, showToast, user } = useAuth();
  const instituteCode = user?.institute_code ?? undefined;
  const [batches, setBatches] = useState<GlueBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [status, setStatus] = useState("");
  const [glueType, setGlueType] = useState("");
  const [query, setQuery] = useState("");
  const [scanMiss, setScanMiss] = useState<string | null>(null);
  const [selected, setSelected] = useState<GlueBatch | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const [newType, setNewType] = useState("");
  const [newBatch, setNewBatch] = useState("");
  const [newPdbSn, setNewPdbSn] = useState("");
  const [newExpiry, setNewExpiry] = useState("");
  const [newBipacks, setNewBipacks] = useState("");
  const [newNote, setNewNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // One shared 1 Hz clock drives every pot-life countdown on the screen.
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getGlueBatches(
      {
        status: status || undefined,
        glue_type: glueType || undefined,
        q: query.trim() || undefined,
        institute: instituteCode,
      },
      controller.signal,
    )
      .then((data) => {
        setBatches(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        if (caught instanceof ApiError && caught.isNetwork) {
          setBatches(filterDemoGlueBatches(status, glueType, query));
          setDemo(true);
        } else {
          setError(errorMessage(caught));
        }
        setLoading(false);
      });
    return () => controller.abort();
  }, [glueType, instituteCode, query, reloadKey, status]);

  // Derived from the loaded data; the active filter value stays listed even
  // when the filtered result no longer contains other types.
  const typeOptions = [
    ...new Set([...batches.map((batch) => batch.glue_type), ...(glueType === "" ? [] : [glueType])]),
  ]
    .filter((value) => value !== "")
    .sort();

  function replaceBatch(batch: GlueBatch) {
    setBatches((current) => current.map((item) => (item.id === batch.id ? batch : item)));
    setSelected((current) => (current !== null && current.id === batch.id ? batch : current));
  }

  async function handleScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = query.trim();
    if (code === "") return;
    setScanMiss(null);
    if (demo) {
      const hit = scanDemoGlueBatch(code);
      if (hit !== undefined) {
        setSelected(hit);
        setQuery("");
      } else {
        setScanMiss(t.glue.scanNotFound(code));
      }
      return;
    }
    try {
      const batch = await scanGlueBatch(code, instituteCode);
      setSelected(batch);
      setQuery("");
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.isNetwork) {
        const hit = scanDemoGlueBatch(code);
        if (hit !== undefined) {
          setDemo(true);
          setSelected(hit);
          setQuery("");
          return;
        }
      }
      setScanMiss(t.glue.scanNotFound(code));
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newType.trim() === "" || newBatch.trim() === "") {
      setFormError(t.glue.formIncomplete);
      return;
    }
    setCreating(true);
    setFormError(null);
    const batchNo = newBatch.trim();
    try {
      if (!demo) {
        await postGlueBatch({
          glue_type: newType.trim(),
          batch_no: batchNo,
          pdb_sn: newPdbSn.trim() || undefined,
          expiry_date: optionalIsoDate(newExpiry),
          bipack_count: newBipacks === "" ? undefined : Number(newBipacks),
          note: newNote.trim() || undefined,
        });
        setReloadKey((key) => key + 1);
      }
      // Demo mode: writes stay client-side no-ops; the toast keeps the flow explorable.
      setNewType("");
      setNewBatch("");
      setNewPdbSn("");
      setNewExpiry("");
      setNewBipacks("");
      setNewNote("");
      showToast(t.glue.created(batchNo));
    } catch (caught: unknown) {
      setFormError(`${t.glue.createFailed}: ${errorMessage(caught)}`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.glueBatches}</h1>
        <span className="sub">{t.glue.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>

      <form className="toolbar" role="search" onSubmit={(event) => void handleScan(event)}>
        <input
          className="search-input"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t.glue.scanPlaceholder}
          aria-label={t.glue.scanLabel}
          autoFocus
        />
        <select
          className="select-input"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          aria-label={t.glue.statusLabel}
        >
          <option value="">{t.glue.allStatuses}</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {statusLabel(value)}
            </option>
          ))}
        </select>
        <select
          className="select-input"
          value={glueType}
          onChange={(event) => setGlueType(event.target.value)}
          aria-label={t.glue.typeLabel}
        >
          <option value="">{t.glue.allTypes}</option>
          {typeOptions.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </form>

      {scanMiss !== null && (
        <div className="info-banner" role="status">
          <span>{scanMiss}</span>
          <button type="button" className="btn" onClick={() => setScanMiss(null)}>
            {t.common.dismiss}
          </button>
        </div>
      )}

      {canWrite && (
        <form className="panel phase4-form" onSubmit={(event) => void handleCreate(event)}>
          <h2 className="section-title">{t.glue.addTitle}</h2>
          <div className="phase4-form-grid">
            <FormField label={t.glue.typeFieldLabel}>
              <input
                className="text-input"
                value={newType}
                onChange={(event) => setNewType(event.target.value)}
                placeholder={t.glue.typePlaceholder}
              />
            </FormField>
            <FormField label={t.glue.batchFieldLabel}>
              <input
                className="text-input mono"
                value={newBatch}
                onChange={(event) => setNewBatch(event.target.value)}
                placeholder={t.glue.batchPlaceholder}
              />
            </FormField>
            <FormField label={t.glue.pdbSnFieldLabel}>
              <input
                className="text-input mono"
                value={newPdbSn}
                onChange={(event) => setNewPdbSn(event.target.value)}
                placeholder={t.glue.pdbSnPlaceholder}
              />
            </FormField>
            <FormField label={t.glue.expiryFieldLabel}>
              <input
                className="text-input"
                type="date"
                value={newExpiry}
                onChange={(event) => setNewExpiry(event.target.value)}
              />
            </FormField>
            <FormField label={t.glue.bipackFieldLabel}>
              <input
                className="short-input"
                type="number"
                min="0"
                value={newBipacks}
                onChange={(event) => setNewBipacks(event.target.value)}
              />
            </FormField>
            <FormField label={t.glue.noteFieldLabel} wide>
              <input
                className="text-input"
                value={newNote}
                onChange={(event) => setNewNote(event.target.value)}
              />
            </FormField>
          </div>
          <div className="phase4-form-actions">
            <button type="submit" className="btn primary" disabled={creating}>
              {creating ? t.common.loading : t.glue.addBtn}
            </button>
            {formError !== null && <span className="error-text">{formError}</span>}
          </div>
        </form>
      )}

      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.glue.loadError}: {error}
          </span>
          <button type="button" className="btn" onClick={() => setReloadKey((key) => key + 1)}>
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : batches.length === 0 ? (
        <p className="state-note">{t.glue.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.glue.colType}</th>
                <th scope="col">{t.glue.colBatch}</th>
                <th scope="col">{t.glue.colPdbSn}</th>
                <th scope="col">{t.glue.colStatus}</th>
                <th scope="col">{t.glue.colExpiry}</th>
                <th scope="col">{t.glue.colPotLife}</th>
                <th scope="col">{t.glue.colUsage}</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <tr className="row-click" key={batch.id} onClick={() => setSelected(batch)}>
                  <td>{batch.glue_type}</td>
                  <td className="mono">{batch.batch_no}</td>
                  <td className="mono muted">{batch.pdb_sn ?? t.common.none}</td>
                  <td>
                    <span className={statusChip(batch.status)}>{statusLabel(batch.status)}</span>
                  </td>
                  <td className="mono muted">
                    {batch.expiry_date === null ? t.common.none : formatTimestamp(batch.expiry_date)}
                  </td>
                  <td>
                    <PotLifeCell batch={batch} nowMs={nowMs} />
                  </td>
                  <td className="mono">{batch.usage_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected !== null && (
        <GlueBatchDetail
          batch={selected}
          demo={demo}
          canWrite={canWrite}
          nowMs={nowMs}
          onClose={() => setSelected(null)}
          onChanged={replaceBatch}
          onReload={() => setReloadKey((key) => key + 1)}
        />
      )}
    </div>
  );
}

/** Inline detail for the opened/scanned batch: lifecycle actions plus the
 * per-component usage log that replaces the glue column of the old sheet. */
function GlueBatchDetail({
  batch,
  demo,
  canWrite,
  nowMs,
  onClose,
  onChanged,
  onReload,
}: {
  batch: GlueBatch;
  demo: boolean;
  canWrite: boolean;
  nowMs: number;
  onClose: () => void;
  onChanged: (batch: GlueBatch) => void;
  onReload: () => void;
}) {
  const { showToast } = useAuth();
  const [usage, setUsage] = useState<GlueUsage[]>([]);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [potLife, setPotLife] = useState("");
  const [component, setComponent] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const closed = batch.status === "expired" || batch.status === "empty";

  useEffect(() => {
    const controller = new AbortController();
    setUsageLoading(true);
    setUsageError(null);
    if (demo) {
      setUsage(makeDemoGlueUsage(batch.id));
      setUsageLoading(false);
      return () => controller.abort();
    }
    getGlueUsage(batch.id, controller.signal)
      .then((data) => {
        setUsage(data);
        setUsageLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setUsageError(`${t.glue.usageFailed}: ${errorMessage(caught)}`);
        setUsageLoading(false);
      });
    return () => controller.abort();
  }, [batch.id, demo]);

  async function mixBatch() {
    setBusy(true);
    try {
      const minutes = potLife === "" ? undefined : Number(potLife);
      let changed: GlueBatch;
      if (demo) {
        const effective = minutes !== undefined ? minutes : batch.pot_life_minutes;
        changed = {
          ...batch,
          status: batch.status === "new" ? "in_use" : batch.status,
          mixed_at: new Date().toISOString(),
          opening_date: batch.opening_date ?? new Date().toISOString(),
          pot_life_minutes: effective,
          pot_life_remaining_seconds: effective === null ? null : effective * 60,
          pot_life_expired: false,
        };
      } else {
        changed = await postGlueBatchMix(batch.id, minutes);
      }
      onChanged(changed);
      setPotLife("");
      showToast(t.glue.mixed(batch.batch_no));
    } catch (caught: unknown) {
      showToast(`${t.glue.mixFailed}: ${errorMessage(caught)}`);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(status: GlueBatchStatus) {
    setBusy(true);
    try {
      if (demo) {
        onChanged({ ...batch, status });
      } else {
        onChanged(await patchGlueBatch(batch.id, { status }));
        onReload();
      }
    } catch (caught: unknown) {
      showToast(`${t.glue.updateFailed}: ${errorMessage(caught)}`);
    } finally {
      setBusy(false);
    }
  }

  async function recordUsage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const sn = component.trim();
    if (sn === "") return;
    setBusy(true);
    try {
      let created: GlueUsage;
      if (demo) {
        created = {
          id: usage.reduce((max, item) => Math.max(max, item.id), 0) + 1,
          glue_batch_id: batch.id,
          component_sn: sn,
          amount_mg: amount === "" ? null : Number(amount),
          note: note.trim() === "" ? null : note.trim(),
          used_by: "anna.abel@example.org",
          used_at: new Date().toISOString(),
        };
      } else {
        created = await postGlueUsage(batch.id, {
          component_sn: sn,
          amount_mg: amount === "" ? undefined : Number(amount),
          note: note.trim() || undefined,
        });
        onReload();
      }
      setUsage((current) => [created, ...current]);
      onChanged({ ...batch, usage_count: batch.usage_count + 1 });
      setComponent("");
      setAmount("");
      setNote("");
      showToast(t.glue.usageRecorded(sn));
    } catch (caught: unknown) {
      showToast(`${t.glue.usageFailed}: ${errorMessage(caught)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel phase4-detail" aria-labelledby="glue-detail-title">
      <div className="phase4-panel-head">
        <div>
          <h2 className="section-title" id="glue-detail-title">
            {batch.glue_type}
          </h2>
          <div className="mono phase4-detail-name">{batch.batch_no}</div>
        </div>
        <span className={statusChip(batch.status)}>{statusLabel(batch.status)}</span>
        <button type="button" className="btn" onClick={onClose}>
          {t.glue.detailClose}
        </button>
      </div>

      <div className="field-grid">
        <Field label={t.glue.colPdbSn} value={batch.pdb_sn ?? t.common.none} mono />
        <Field
          label={t.glue.colExpiry}
          value={batch.expiry_date === null ? t.common.none : formatTimestamp(batch.expiry_date)}
        />
        <Field label={t.glue.colPotLife} value={potLifeText(batch, nowMs)} mono />
        <Field
          label={t.glue.bipackFieldLabel}
          value={batch.bipack_count === null ? t.common.none : String(batch.bipack_count)}
          mono
        />
        <Field label={t.glue.colUsage} value={String(batch.usage_count)} mono />
        <Field label={t.glue.noteFieldLabel} value={batch.note ?? t.common.none} />
      </div>

      {canWrite && !closed && (
        <div className="phase4-action-bar">
          <label className="field-label" htmlFor={`glue-pot-life-${batch.id}`}>
            {t.glue.mixPotLifeLabel}
          </label>
          <input
            id={`glue-pot-life-${batch.id}`}
            className="short-input"
            type="number"
            min="1"
            max="1440"
            value={potLife}
            onChange={(event) => setPotLife(event.target.value)}
            placeholder={t.glue.mixPotLifePlaceholder}
          />
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() => void mixBatch()}
          >
            {t.glue.mixBtn}
          </button>
        </div>
      )}
      {canWrite && (
        <div className="phase4-action-bar">
          <button
            type="button"
            className="btn"
            disabled={busy || batch.status === "empty"}
            onClick={() => void setStatus("empty")}
          >
            {t.glue.markEmpty}
          </button>
          <button
            type="button"
            className="btn danger"
            disabled={busy || batch.status === "expired"}
            onClick={() => void setStatus("expired")}
          >
            {t.glue.markExpired}
          </button>
        </div>
      )}

      <div className="phase4-subsection">
        <h3 className="section-title">{t.glue.usageTitle}</h3>
        {canWrite && !closed && (
          <form className="phase4-action-bar" onSubmit={(event) => void recordUsage(event)}>
            <input
              className="text-input mono"
              value={component}
              onChange={(event) => setComponent(event.target.value)}
              placeholder={t.glue.usageSnLabel}
              aria-label={t.glue.usageSnLabel}
            />
            <input
              className="short-input"
              type="number"
              min="0"
              step="any"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder={t.glue.usageAmountLabel}
              aria-label={t.glue.usageAmountLabel}
            />
            <input
              className="text-input"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={t.glue.usageNoteLabel}
              aria-label={t.glue.usageNoteLabel}
            />
            <button type="submit" className="btn primary" disabled={busy || component.trim() === ""}>
              {t.glue.usageBtn}
            </button>
          </form>
        )}
        {usageError !== null ? (
          <div className="error-banner" role="alert">
            <span>{usageError}</span>
          </div>
        ) : usageLoading ? (
          <p className="state-note">{t.common.loading}</p>
        ) : usage.length === 0 ? (
          <p className="state-note">{t.glue.usageEmpty}</p>
        ) : (
          <div className="phase4-table-wrap">
            <table className="data-table compact-table">
              <thead>
                <tr>
                  <th scope="col">{t.glue.usageColComponent}</th>
                  <th scope="col">{t.glue.usageColAmount}</th>
                  <th scope="col">{t.glue.usageColBy}</th>
                  <th scope="col">{t.glue.usageColWhen}</th>
                </tr>
              </thead>
              <tbody>
                {usage.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.component_sn}</td>
                    <td className="mono">{item.amount_mg ?? t.common.none}</td>
                    <td>{item.used_by}</td>
                    <td className="muted">{formatRelative(item.used_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function FormField({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={wide ? "phase4-field phase4-field-wide" : "phase4-field"}>
      <span className="field-label">{label}</span>
      {children}
    </label>
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
