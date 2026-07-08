import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  DEFAULT_OUTBOX_CONTRACT,
  getOutbox,
  getOutboxContract,
  postOutboxTransition,
} from "../api";
import type { OutboxAction, OutboxContract, OutboxStatus } from "../api";
import { makeDemoOutbox } from "../demoData";
import { formatTimestamp, t } from "../i18n";

const ACTOR = "ui-demo-user";

/** Status → chip color. Neutral: draft/validated; amber: in flight; green/red/muted: terminal-ish. */
const STATUS_CHIP: Record<OutboxStatus, string> = {
  draft: "chip neutral",
  validated: "chip neutral",
  approved: "chip amber",
  submitted: "chip amber",
  confirmed: "chip green",
  failed: "chip red",
  cancelled: "chip muted",
};

function chipClass(status: string): string {
  return STATUS_CHIP[status as OutboxStatus] ?? "chip neutral";
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function OutboxScreen() {
  const [actions, setActions] = useState<OutboxAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [contract, setContract] = useState<OutboxContract>(DEFAULT_OUTBOX_CONTRACT);
  // Demo outbox lives in a ref so local transitions survive filter changes.
  const demoStore = useRef<OutboxAction[] | null>(null);

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (opts?.silent !== true) setLoading(true);
      setError(null);
      try {
        const data = await getOutbox(statusFilter || undefined);
        setActions(data);
        setDemo(false);
      } catch (err) {
        if (err instanceof ApiError && err.isNetwork) {
          if (demoStore.current === null) demoStore.current = makeDemoOutbox();
          const all = demoStore.current;
          setActions(statusFilter === "" ? all : all.filter((a) => a.status === statusFilter));
          setDemo(true);
        } else {
          setError(errorMessage(err));
        }
      } finally {
        setLoading(false);
      }
    },
    [statusFilter],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const ctrl = new AbortController();
    getOutboxContract(ctrl.signal)
      .then(setContract)
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (!(err instanceof ApiError && err.isNetwork)) {
          setNotice(errorMessage(err));
        }
      });
    return () => ctrl.abort();
  }, []);

  async function handleTransition(action: OutboxAction, to: OutboxStatus) {
    setNotice(null);
    if (demo && demoStore.current !== null) {
      // Local state machine so the screen stays explorable without a backend.
      demoStore.current = demoStore.current.map((a) =>
        a.id === action.id
          ? {
              ...a,
              status: to,
              error: to === "failed" ? "Simulated PDB rejection (demo)" : null,
              attempts: to === "submitted" ? a.attempts + 1 : a.attempts,
              updated_at: new Date().toISOString(),
            }
          : a,
      );
      const all = demoStore.current;
      setActions(statusFilter === "" ? all : all.filter((a) => a.status === statusFilter));
      return;
    }
    setBusyId(action.id);
    try {
      await postOutboxTransition(action.id, { to, actor: ACTOR });
      await load({ silent: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNotice(`${t.outbox.transitionRejected}: ${err.message}`);
        await load({ silent: true }); // server-side state may have moved on
      } else if (err instanceof ApiError && err.isNetwork) {
        setNotice(t.outbox.transitionNetwork);
      } else {
        setNotice(errorMessage(err));
      }
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="screen">
      {demo && (
        <div className="toolbar">
          <span className="badge warn">{t.common.demoBadge}</span>
          <span className="muted">{t.common.demoNote}</span>
        </div>
      )}
      <div className="toolbar">
        <select
          className="select-input"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label={t.outbox.statusFilterLabel}
        >
          <option value="">{t.outbox.allStatuses}</option>
          {contract.statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      {notice !== null && (
        <div className="error-banner" role="alert">
          <span>{notice}</span>
          <button className="btn" onClick={() => setNotice(null)}>
            OK
          </button>
        </div>
      )}
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.outbox.loadError}: {error}
          </span>
          <button className="btn" onClick={() => void load()}>
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : actions.length === 0 ? (
        <p className="state-note">{t.outbox.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.outbox.colId}</th>
                <th scope="col">{t.outbox.colKind}</th>
                <th scope="col">{t.outbox.colPayload}</th>
                <th scope="col">{t.outbox.colStatus}</th>
                <th scope="col">{t.outbox.colAttempts}</th>
                <th scope="col">{t.outbox.colCreatedBy}</th>
                <th scope="col">{t.outbox.colUpdated}</th>
                <th scope="col">{t.outbox.colActions}</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((a) => {
                const targets = contract.transitions[a.status as OutboxStatus] ?? [];
                return (
                  <tr key={a.id}>
                    <td className="mono">#{a.id}</td>
                    <td className="mono">{a.kind}</td>
                    <td>
                      <details className="payload-details">
                        <summary>{t.outbox.showPayload}</summary>
                        <pre>{JSON.stringify(a.payload, null, 2)}</pre>
                      </details>
                    </td>
                    <td>
                      <span className={chipClass(a.status)}>{a.status}</span>
                      {a.status === "failed" && a.error !== null && (
                        <div className="error-text">{a.error}</div>
                      )}
                    </td>
                    <td>{a.attempts}</td>
                    <td>{a.created_by}</td>
                    <td className="muted">{formatTimestamp(a.updated_at)}</td>
                    <td>
                      <div className="row-actions">
                        {targets.length === 0 && <span className="muted">{t.outbox.noActions}</span>}
                        {targets.map((to) => (
                          <button
                            key={to}
                            className={to === "cancelled" || to === "failed" ? "btn danger" : "btn"}
                            disabled={busyId === a.id}
                            onClick={() => void handleTransition(a, to)}
                          >
                            {a.status === "failed" && to === "submitted"
                              ? t.outbox.retryLabel
                              : t.outbox.transitions[to]}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
