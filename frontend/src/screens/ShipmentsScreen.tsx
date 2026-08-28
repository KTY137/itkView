import { useEffect, useState } from "react";
import {
  ApiError,
  getInstitutes,
  getShipments,
  postShipmentReception,
  postShipmentSync,
} from "../api";
import type {
  Institute,
  Shipment,
  ShipmentChecklistItem,
  ShipmentDirection,
  ShipmentReceptionBody,
  ShipmentReceptionItem,
  ShipmentReceptionTestStatus,
} from "../api";
import { useAuth } from "../auth";
import { filterDemoShipments } from "../demoData";
import { formatRelative, formatTimestamp, t } from "../i18n";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** PDB shipment status → chip class. The raw status string stays visible so we
 * never hide unexpected PDB values behind a translation. */
function statusChip(status: string): string {
  const normalized = status.toLowerCase().replace(/[\s_-]/g, "");
  if (normalized === "delivered") return "chip green";
  if (normalized === "intransit") return "chip amber";
  return "chip neutral";
}

function receptionChip(status: Shipment["reception_status"]): string {
  if (status === "pending") return "chip amber";
  if (status === "done") return "chip green";
  return "chip neutral";
}

function receptionLabel(status: Shipment["reception_status"]): string {
  if (status === "pending") return t.shipments.receptionPending;
  if (status === "in_progress") return t.shipments.receptionInProgress;
  return t.shipments.receptionDone;
}

function directionLabel(direction: ShipmentDirection): string {
  if (direction === "incoming") return t.shipments.directionIncoming;
  if (direction === "outgoing") return t.shipments.directionOutgoing;
  if (direction === "internal") return t.shipments.directionInternal;
  return t.shipments.directionUnknown;
}

function receptionTestChip(status: ShipmentReceptionTestStatus): string {
  if (status === "passed") return "chip green";
  if (status === "failed") return "chip red";
  if (status === "pending") return "chip queued";
  return "chip amber";
}

function receptionTestLabel(status: ShipmentReceptionTestStatus): string {
  if (status === "passed") return t.shipments.testPassed;
  if (status === "failed") return t.shipments.testFailed;
  if (status === "pending") return t.shipments.testPending;
  return t.shipments.testMissing;
}

/** The receiving check applies where the shipment arrives at this site. */
function isReceivable(shipment: Shipment): boolean {
  return shipment.direction === "incoming" || shipment.direction === "internal";
}

/** Working list for the receiving check: every shipped item gets a row, seeded
 * from any saved reception state; saved rows for since-removed SNs survive. */
function mergeReceptionItems(shipment: Shipment): ShipmentReceptionItem[] {
  const saved = new Map(shipment.reception_items.map((item) => [item.sn, item]));
  const merged: ShipmentReceptionItem[] = shipment.items.map((item) => {
    const hit = saved.get(item.sn);
    return hit !== undefined ? { ...hit } : { sn: item.sn, received: false };
  });
  for (const item of shipment.reception_items) {
    if (!shipment.items.some((shipped) => shipped.sn === item.sn)) merged.push({ ...item });
  }
  return merged;
}

const DIRECTIONS: ShipmentDirection[] = ["incoming", "outgoing", "internal"];
const RECEPTION_STATES: Shipment["reception_status"][] = ["pending", "in_progress", "done"];

/** Phase-4 shipments: read-only PDB shipment mirror per direction plus the
 * local receiving check (checklist, per-item confirmation, note). */
export default function ShipmentsScreen({
  onOpenComponent,
  onAddTest,
}: {
  onOpenComponent: (sn: string) => void;
  onAddTest: (sn: string, testType: string) => void;
}) {
  const { canWrite, canSync, showToast, user } = useAuth();
  const [shipments, setShipments] = useState<Shipment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [direction, setDirection] = useState("");
  const [reception, setReception] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [selectedInstitute, setSelectedInstitute] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const homeInstitute = user?.institute_code ?? null;

  useEffect(() => {
    const controller = new AbortController();
    getInstitutes(controller.signal)
      .then((data) => {
        const scoped =
          homeInstitute === null
            ? data
            : data.filter((institute) => institute.code === homeInstitute);
        setInstitutes(scoped);
        setSelectedInstitute((current) => {
          if (current !== "" && scoped.some((i) => i.code === current)) return current;
          if (homeInstitute !== null && scoped.some((i) => i.code === homeInstitute)) {
            return homeInstitute;
          }
          return scoped[0]?.code ?? "";
        });
      })
      .catch(() => setInstitutes([]));
    return () => controller.abort();
  }, [homeInstitute]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getShipments(
      {
        direction: direction || undefined,
        reception: reception || undefined,
        q: query.trim() || undefined,
      },
      controller.signal,
    )
      .then((data) => {
        setShipments(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        if (caught instanceof ApiError && caught.isNetwork) {
          setShipments(filterDemoShipments(direction, reception, query));
          setDemo(true);
        } else {
          setError(errorMessage(caught));
        }
        setLoading(false);
      });
    return () => controller.abort();
  }, [direction, query, reception, reloadKey]);

  async function handleSync() {
    if (selectedInstitute === "") {
      showToast(t.shipments.syncNeedsInstitute);
      return;
    }
    setSyncing(true);
    try {
      const result = await postShipmentSync(selectedInstitute);
      showToast(
        t.shipments.syncComplete(
          result.institute_code,
          result.created,
          result.updated,
          result.unchanged,
        ),
      );
      setReloadKey((key) => key + 1);
    } catch (caught) {
      showToast(`${t.shipments.syncFailed}: ${errorMessage(caught)}`);
    } finally {
      setSyncing(false);
    }
  }

  function replaceShipment(updated: Shipment) {
    setShipments((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
  }

  const selected =
    selectedId === null ? null : (shipments.find((s) => s.id === selectedId) ?? null);

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.shipments}</h1>
        <span className="sub">{t.shipments.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>

      {!demo && canSync && (
        <div className="panel compact-panel">
          <div className="toolbar">
            <label className="control-label" htmlFor="shipment-sync-institute">
              {t.shipments.instituteLabel}
            </label>
            <select
              id="shipment-sync-institute"
              className="select-input"
              value={selectedInstitute}
              onChange={(event) => setSelectedInstitute(event.target.value)}
            >
              {institutes.length === 0 ? (
                <option value="">{t.shipments.noInstitutes}</option>
              ) : (
                institutes.map((institute) => (
                  <option key={institute.code} value={institute.code}>
                    {institute.code} - {institute.name}
                  </option>
                ))
              )}
            </select>
            <button
              type="button"
              className="btn"
              disabled={syncing || selectedInstitute === ""}
              onClick={() => void handleSync()}
            >
              {syncing ? t.common.loading : t.shipments.syncBtn}
            </button>
          </div>
        </div>
      )}

      <div className="toolbar">
        <select
          className="select-input"
          value={direction}
          onChange={(event) => setDirection(event.target.value)}
          aria-label={t.shipments.directionLabel}
        >
          <option value="">{t.shipments.allDirections}</option>
          {DIRECTIONS.map((value) => (
            <option key={value} value={value}>
              {directionLabel(value)}
            </option>
          ))}
        </select>
        <select
          className="select-input"
          value={reception}
          onChange={(event) => setReception(event.target.value)}
          aria-label={t.shipments.receptionLabel}
        >
          <option value="">{t.shipments.allReception}</option>
          {RECEPTION_STATES.map((value) => (
            <option key={value} value={value}>
              {receptionLabel(value)}
            </option>
          ))}
        </select>
        <input
          className="search-input"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t.shipments.searchPlaceholder}
          aria-label={t.shipments.searchPlaceholder}
          autoFocus
        />
      </div>

      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.shipments.loadError}: {error}
          </span>
          <button
            type="button"
            className="btn"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : shipments.length === 0 ? (
        <p className="state-note">{t.shipments.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.shipments.colName}</th>
                <th scope="col">{t.shipments.colFrom}</th>
                <th scope="col">{t.shipments.colTo}</th>
                <th scope="col">{t.shipments.colStatus}</th>
                <th scope="col">{t.shipments.colSent}</th>
                <th scope="col">{t.shipments.colItems}</th>
                <th scope="col">{t.shipments.colReceptionTests}</th>
                <th scope="col">{t.shipments.colReception}</th>
              </tr>
            </thead>
            <tbody>
              {shipments.map((shipment) => (
                <tr
                  className="row-click"
                  key={shipment.id}
                  onClick={() => setSelectedId(shipment.id)}
                >
                  <td>
                    {shipment.name !== null ? (
                      <>
                        <div>{shipment.name}</div>
                        <div className="mono muted">{shipment.pdb_id}</div>
                      </>
                    ) : (
                      <div className="mono">{shipment.pdb_id}</div>
                    )}
                  </td>
                  <td>{shipment.sender_code}</td>
                  <td>{shipment.recipient_code}</td>
                  <td>
                    <span className={statusChip(shipment.status)}>{shipment.status}</span>
                  </td>
                  <td className="mono muted">
                    {shipment.sent_at === null
                      ? t.common.none
                      : formatTimestamp(shipment.sent_at)}
                  </td>
                  <td className="mono">{shipment.items.length}</td>
                  <td>
                    {shipment.reception_tests_configured ? (
                      <span className={receptionTestChip(shipment.reception_test_status)}>
                        {receptionTestLabel(shipment.reception_test_status)}
                      </span>
                    ) : (
                      <span className="muted">{t.shipments.testsNotRequired}</span>
                    )}
                  </td>
                  <td>
                    {isReceivable(shipment) ? (
                      <span className={receptionChip(shipment.reception_status)}>
                        {receptionLabel(shipment.reception_status)}
                      </span>
                    ) : (
                      <span className="muted">{t.common.none}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected !== null && (
        <ShipmentDetail
          key={selected.id}
          shipment={selected}
          demo={demo}
          canWrite={canWrite}
          onClose={() => setSelectedId(null)}
          onChanged={replaceShipment}
          onOpenComponent={onOpenComponent}
          onAddTest={onAddTest}
        />
      )}
    </div>
  );
}

function ShipmentDetail({
  shipment,
  demo,
  canWrite,
  onClose,
  onChanged,
  onOpenComponent,
  onAddTest,
}: {
  shipment: Shipment;
  demo: boolean;
  canWrite: boolean;
  onClose: () => void;
  onChanged: (shipment: Shipment) => void;
  onOpenComponent: (sn: string) => void;
  onAddTest: (sn: string, testType: string) => void;
}) {
  const { showToast, user } = useAuth();
  // Working copy of the receiving check; the component remounts per shipment
  // (keyed by id in the parent), so plain initializers are enough.
  const [checklist, setChecklist] = useState<ShipmentChecklistItem[]>(() =>
    shipment.reception_checklist.map((entry) => ({ ...entry })),
  );
  const [items, setItems] = useState<ShipmentReceptionItem[]>(() =>
    mergeReceptionItems(shipment),
  );
  const [note, setNote] = useState(shipment.reception_note ?? "");
  const [busy, setBusy] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [overrideTests, setOverrideTests] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const testsAllowDone =
    !shipment.reception_tests_configured || shipment.reception_test_status === "passed";
  const canAdminOverride = user?.role === "admin";

  function toggleChecklist(index: number) {
    setChecklist((current) =>
      current.map((entry, i) => (i === index ? { ...entry, done: !entry.done } : entry)),
    );
  }

  function toggleItem(sn: string) {
    setItems((current) =>
      current.map((item) => (item.sn === sn ? { ...item, received: !item.received } : item)),
    );
  }

  async function save(statusOverride?: "in_progress" | "done") {
    setBusy(true);
    setOperationError(null);
    try {
      const body: ShipmentReceptionBody = {
        checklist,
        items,
        note: note.trim(),
      };
      if (statusOverride !== undefined) body.status = statusOverride;
      if (statusOverride === "done" && !testsAllowDone && overrideTests) {
        body.test_override = true;
        body.test_override_reason = overrideReason.trim();
      }
      const updated = demo
        ? ({
            ...shipment,
            reception_status:
              statusOverride ??
              (shipment.reception_status === "pending"
                ? "in_progress"
                : shipment.reception_status),
            reception_checklist: checklist.map((entry) => ({ ...entry })),
            reception_items: items.map((item) => ({ ...item })),
            reception_note: note.trim() === "" ? null : note.trim(),
            reception_by: user?.email ?? "demo.operator@example.org",
            reception_updated_at: new Date().toISOString(),
          } satisfies Shipment)
        : await postShipmentReception(shipment.id, body);
      onChanged(updated);
      setOverrideTests(false);
      setOverrideReason("");
      showToast(t.shipments.receptionSaved);
    } catch (caught) {
      setOperationError(`${t.shipments.receptionFailed}: ${errorMessage(caught)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel phase4-detail" aria-label={t.shipments.detailTitle}>
      <div className="phase4-panel-head">
        <div>
          <h2 className="section-title">{shipment.name ?? shipment.pdb_id}</h2>
          <div className="mono phase4-detail-name">
            {shipment.sender_code} → {shipment.recipient_code}
          </div>
        </div>
        <span className={statusChip(shipment.status)}>{shipment.status}</span>
        {isReceivable(shipment) && (
          <span className={receptionChip(shipment.reception_status)}>
            {receptionLabel(shipment.reception_status)}
          </span>
        )}
        <button type="button" className="btn" onClick={onClose}>
          {t.shipments.detailClose}
        </button>
      </div>

      <div className="field-grid">
        <Value label={t.shipments.colName} value={shipment.pdb_id} mono />
        <Value
          label={t.shipments.directionLabel}
          value={directionLabel(shipment.direction)}
        />
        <Value
          label={t.shipments.colSent}
          value={shipment.sent_at === null ? t.common.none : formatTimestamp(shipment.sent_at)}
        />
      </div>

      <div className="phase4-subsection">
        <h3 className="section-title">{t.shipments.itemsTitle(shipment.items.length)}</h3>
        {shipment.items.length === 0 ? (
          <p className="state-note">{t.shipments.itemsEmpty}</p>
        ) : (
          <ul className="phase4-check-list">
            {shipment.items.map((item) => (
              <li className="reception-item" key={item.sn}>
                <div className="reception-item-head">
                  <button
                    type="button"
                    className="link-btn mono"
                    onClick={() => onOpenComponent(item.sn)}
                  >
                    {item.sn}
                  </button>
                  {item.component_type !== undefined && item.component_type !== null && (
                    <span className="chip neutral">{item.component_type}</span>
                  )}
                  {item.reception_tests_configured ? (
                    <span className={receptionTestChip(item.reception_test_status)}>
                      {receptionTestLabel(item.reception_test_status)}
                    </span>
                  ) : (
                    <span className="muted">{t.shipments.testsNotRequired}</span>
                  )}
                </div>
                {item.reception_tests.length > 0 && (
                  <div className="reception-test-list">
                    {item.reception_tests.map((test) => (
                      <div className="reception-test-row" key={test.test_type}>
                        <span className="mono">{test.test_type}</span>
                        <span className={receptionTestChip(test.status)}>
                          {receptionTestLabel(test.status)}
                        </span>
                        {(test.status === "missing" || test.status === "failed") && canWrite && (
                          <button
                            type="button"
                            className="btn"
                            onClick={() => onAddTest(item.sn, test.test_type)}
                          >
                            {t.shipments.recordTest}
                          </button>
                        )}
                      </div>
                    ))}
                    {canWrite && (
                      <p className="muted reception-write-scope-hint">
                        {item.submittable
                          ? t.shipments.dummyWriteHint
                          : t.shipments.stagedOnlyHint}
                      </p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="phase4-subsection">
        <h3 className="section-title">{t.shipments.receptionLabel}</h3>
        {shipment.reception_tests_configured && (
          <div
            className={
              testsAllowDone
                ? "info-banner reception-test-gate is-passed"
                : "error-banner reception-test-gate"
            }
            role="status"
          >
            <div>
              <strong>{t.shipments.receptionTestsTitle}</strong>
              <p>
                {testsAllowDone
                  ? t.shipments.testsReadyForDone
                  : t.shipments.testsBlockDone(
                      receptionTestLabel(shipment.reception_test_status),
                    )}
              </p>
            </div>
            <span className={receptionTestChip(shipment.reception_test_status)}>
              {receptionTestLabel(shipment.reception_test_status)}
            </span>
          </div>
        )}
        <div className="phase4-split">
          <div className="phase4-field">
            <span className="field-label">{t.shipments.checklistTitle}</span>
            {checklist.length === 0 ? (
              <span className="muted">{t.common.none}</span>
            ) : (
              <ul className="phase4-check-list">
                {checklist.map((entry, index) => (
                  <li key={`${index}-${entry.label}`}>
                    {canWrite ? (
                      <label>
                        <input
                          type="checkbox"
                          checked={entry.done}
                          disabled={busy}
                          onChange={() => toggleChecklist(index)}
                        />
                        <span>{entry.label}</span>
                      </label>
                    ) : (
                      <>
                        <span>{entry.label}</span>
                        <span className={entry.done ? "chip green" : "chip neutral"}>
                          {entry.done ? t.common.yes : t.common.no}
                        </span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="phase4-field">
            <span className="field-label">{t.shipments.itemReceived}</span>
            {items.length === 0 ? (
              <span className="muted">{t.common.none}</span>
            ) : (
              <ul className="phase4-check-list">
                {items.map((item) => (
                  <li key={item.sn}>
                    {canWrite ? (
                      <label>
                        <input
                          type="checkbox"
                          checked={item.received}
                          disabled={busy}
                          aria-label={`${t.shipments.itemReceived}: ${item.sn}`}
                          onChange={() => toggleItem(item.sn)}
                        />
                        <span className="mono">{item.sn}</span>
                      </label>
                    ) : (
                      <>
                        <span className="mono">{item.sn}</span>
                        <span className={item.received ? "chip green" : "chip neutral"}>
                          {item.received ? t.common.yes : t.common.no}
                        </span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        {canWrite ? (
          <label className="phase4-field">
            <span className="field-label">{t.shipments.receptionNoteLabel}</span>
            <textarea
              className="phase4-textarea"
              value={note}
              disabled={busy}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>
        ) : (
          <div className="phase4-field">
            <span className="field-label">{t.shipments.receptionNoteLabel}</span>
            <p className="state-note">{note.trim() || t.common.none}</p>
          </div>
        )}
        {shipment.reception_by !== null && shipment.reception_updated_at !== null && (
          <p className="phase4-meta muted">
            {t.shipments.lastEdit(shipment.reception_by)} ·{" "}
            {formatRelative(shipment.reception_updated_at)}
          </p>
        )}
        {canWrite && !testsAllowDone && shipment.reception_status !== "done" && (
          canAdminOverride ? (
            <div className="reception-override">
              <label className="reception-override-toggle">
                <input
                  type="checkbox"
                  checked={overrideTests}
                  disabled={busy}
                  onChange={(event) => setOverrideTests(event.target.checked)}
                />
                <span>{t.shipments.overrideTestsLabel}</span>
              </label>
              {overrideTests && (
                <label className="phase4-field">
                  <span className="field-label">{t.shipments.overrideReasonLabel}</span>
                  <textarea
                    className="phase4-textarea"
                    value={overrideReason}
                    maxLength={500}
                    disabled={busy}
                    placeholder={t.shipments.overrideReasonPlaceholder}
                    onChange={(event) => setOverrideReason(event.target.value)}
                  />
                </label>
              )}
              <p className="muted phase4-copy">{t.shipments.overrideAuditHint}</p>
            </div>
          ) : (
            <p className="muted phase4-copy">{t.shipments.testsNeedAdminOverride}</p>
          )
        )}
        {canWrite && (
          <div className="phase4-form-actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={() => void save()}
            >
              {t.shipments.saveReception}
            </button>
            {shipment.reception_status === "done" ? (
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => void save("in_progress")}
              >
                {t.shipments.reopen}
              </button>
            ) : (
              <button
                type="button"
                className="btn"
                disabled={
                  busy ||
                  (!testsAllowDone &&
                    (!canAdminOverride || !overrideTests || overrideReason.trim() === ""))
                }
                onClick={() => void save("done")}
              >
                {!testsAllowDone && overrideTests
                  ? t.shipments.markDoneWithOverride
                  : t.shipments.markDone}
              </button>
            )}
          </div>
        )}
      </div>

      {operationError !== null && (
        <div className="error-banner" role="alert">
          <span>{operationError}</span>
        </div>
      )}
    </section>
  );
}

function Value({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="field-label">{label}</div>
      <div className={mono ? "field-value mono" : "field-value"}>{value}</div>
    </div>
  );
}
