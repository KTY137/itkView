// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-ad9bbce8dac4
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  deleteTool,
  getInstitutes,
  getTools,
  patchTool,
  postTool,
  postToolSync,
  scanTool,
} from "../api";
import type {
  Institute,
  Tool,
  ToolCreateBody,
  ToolStatus,
  ToolUpdateBody,
} from "../api";
import { useAuth } from "../auth";
import {
  makeDemoTools,
  removeDemoTool,
  resetDemoTools,
  upsertDemoTool,
} from "../demoData";
import { t } from "../i18n";

const STATUSES: ToolStatus[] = ["active", "flagged", "blacklisted"];
const DEFAULT_KINDS = ["jig", "pickup_tool", "panel", "tool"];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusChip(status: ToolStatus): string {
  if (status === "active") return "chip green";
  if (status === "flagged") return "chip amber";
  return "chip red";
}

function normalizeTypes(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[\s,;]+/)
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean),
    ),
  ];
}

function filterToolRows(
  rows: Tool[],
  kind: string,
  fits: string,
  status: string,
): Tool[] {
  return rows.filter(
    (tool) =>
      (kind === "" || tool.kind === kind) &&
      (fits === "" || tool.compatible_types.includes(fits)) &&
      (status === "" || tool.status === status),
  );
}

/** Full local tool registry: scanner lookup, mirror refresh, structured
 * create/edit/remove, and explicit active/flagged/blacklisted management. */
export default function ToolsScreen() {
  const { canWrite, canSync, isAdmin, user, demo: authDemo, showToast } = useAuth();
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(authDemo);
  const [kind, setKind] = useState("");
  const [fits, setFits] = useState("");
  const [status, setStatus] = useState("");
  const [scanText, setScanText] = useState("");
  const [scanned, setScanned] = useState<Tool | null>(null);
  const [scanMiss, setScanMiss] = useState<string | null>(null);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [selectedInstitute, setSelectedInstitute] = useState(user?.institute_code ?? "");
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [editor, setEditor] = useState<Tool | "create" | null>(null);
  const [busyToolId, setBusyToolId] = useState<number | null>(null);
  const demoStore = useRef<Tool[]>(makeDemoTools());

  useEffect(() => {
    if (authDemo) {
      setInstitutes([]);
      setSelectedInstitute((current) => current || user?.institute_code || "TUDO");
      return;
    }
    const controller = new AbortController();
    getInstitutes(controller.signal)
      .then((data) => {
        setInstitutes(data);
        setSelectedInstitute((current) => {
          const own = user?.institute_code;
          if (own !== null && own !== undefined) return own;
          return data.some((institute) => institute.code === current)
            ? current
            : (data[0]?.code ?? "");
        });
      })
      .catch(() => setInstitutes([]));
    return () => controller.abort();
  }, [authDemo, user?.institute_code]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    if (authDemo) {
      setTools(filterToolRows(demoStore.current, kind, fits, status));
      setDemo(true);
      setLoading(false);
      return () => controller.abort();
    }
    getTools(
      {
        kind: kind || undefined,
        fits: fits || undefined,
        status: (status || undefined) as ToolStatus | undefined,
        institute: selectedInstitute || undefined,
      },
      controller.signal,
    )
      .then((data) => {
        setTools(data);
        setDemo(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        if (caught instanceof ApiError && caught.isNetwork) {
          setTools(filterToolRows(demoStore.current, kind, fits, status));
          setDemo(true);
        } else {
          setError(errorMessage(caught));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [authDemo, fits, kind, reloadKey, selectedInstitute, status]);

  const kindOptions = useMemo(
    () => [...new Set([...DEFAULT_KINDS, ...tools.map((tool) => tool.kind)])].sort(),
    [tools],
  );
  const typeOptions = useMemo(
    () => [...new Set(tools.flatMap((tool) => tool.compatible_types))].sort(),
    [tools],
  );

  function replaceTool(next: Tool) {
    if (demo) {
      upsertDemoTool(next);
      demoStore.current = makeDemoTools();
      setTools(filterToolRows(demoStore.current, kind, fits, status));
      setScanned((current) => (current?.id === next.id ? next : current));
      return;
    }
    setTools((current) => {
      const replaced = current.some((tool) => tool.id === next.id)
        ? current.map((tool) => (tool.id === next.id ? next : tool))
        : [...current, next];
      return replaced.sort(
        (left, right) =>
          left.kind.localeCompare(right.kind) || left.code.localeCompare(right.code),
      );
    });
    setScanned((current) => (current?.id === next.id ? next : current));
  }

  async function handleScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = scanText.trim();
    if (code === "") return;
    setScanMiss(null);
    try {
      const tool = demo
        ? (demoStore.current.find(
            (item) =>
              item.code.toUpperCase() === code.toUpperCase() ||
              (item.rfid ?? "").toUpperCase() === code.toUpperCase() ||
              (item.label ?? "").toUpperCase() === code.toUpperCase(),
          ) ?? null)
        : await scanTool(code, selectedInstitute || undefined);
      if (tool === null) throw new Error(t.tools.scanNotFound(code));
      setScanned(tool);
      setScanText("");
    } catch (caught: unknown) {
      setScanned(null);
      setScanMiss(
        caught instanceof ApiError && caught.status === 404
          ? t.tools.scanNotFound(code)
          : errorMessage(caught),
      );
    }
  }

  async function handleMirrorSync() {
    if (selectedInstitute === "") {
      setSyncNotice(t.tools.syncNeedsInstitute);
      return;
    }
    setSyncing(true);
    setSyncNotice(null);
    try {
      if (demo) {
        resetDemoTools();
        demoStore.current = makeDemoTools();
        setTools(filterToolRows(demoStore.current, kind, fits, status));
        setSyncNotice(t.tools.demoSyncComplete);
      } else {
        const result = await postToolSync(selectedInstitute);
        setSyncNotice(
          t.tools.syncComplete(
            result.institute_code,
            result.created,
            result.updated,
            result.unchanged,
            result.skipped,
          ),
        );
        setReloadKey((value) => value + 1);
      }
    } catch (caught: unknown) {
      setSyncNotice(`${t.tools.syncFailed}: ${errorMessage(caught)}`);
    } finally {
      setSyncing(false);
    }
  }

  async function saveEditor(body: ToolCreateBody | ToolUpdateBody) {
    try {
      if (editor === "create") {
        let created: Tool;
        if (demo) {
          const create = body as ToolCreateBody;
          created = {
            id: Math.max(1_000, ...demoStore.current.map((tool) => tool.id + 1)),
            institute_id: 1,
            created_at: new Date().toISOString(),
            kind: create.kind,
            code: create.code,
            label: create.label ?? null,
            rfid: create.rfid ?? null,
            compatible_types: create.compatible_types,
            status: create.status ?? "active",
          };
        } else {
          created = await postTool({
            ...(body as ToolCreateBody),
            institute_code: selectedInstitute || undefined,
          });
        }
        replaceTool(created);
        showToast(t.tools.created(created.code));
      } else if (editor !== null) {
        const updated = demo
          ? { ...editor, ...(body as ToolUpdateBody) }
          : await patchTool(editor.id, body as ToolUpdateBody);
        replaceTool(updated);
        showToast(t.tools.updated(updated.code));
      }
      setEditor(null);
    } catch (caught: unknown) {
      throw new Error(errorMessage(caught));
    }
  }

  async function changeStatus(tool: Tool, next: ToolStatus) {
    setBusyToolId(tool.id);
    try {
      const updated = demo
        ? { ...tool, status: next }
        : await patchTool(tool.id, { status: next });
      replaceTool(updated);
      showToast(t.tools.statusUpdated(tool.code, next));
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setBusyToolId(null);
    }
  }

  async function removeTool(tool: Tool) {
    if (!window.confirm(t.tools.deleteConfirm(tool.code))) return;
    setBusyToolId(tool.id);
    try {
      if (!demo) await deleteTool(tool.id);
      if (demo) {
        removeDemoTool(tool.id);
        demoStore.current = makeDemoTools();
      }
      setTools((current) => current.filter((item) => item.id !== tool.id));
      setScanned((current) => (current?.id === tool.id ? null : current));
      setEditor(null);
      showToast(t.tools.deleted(tool.code));
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setBusyToolId(null);
    }
  }

  return (
    <div className="screen tools-screen">
      <div className="sc-head">
        <h1>{t.nav.tools}</h1>
        <span className="sub">{t.tools.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
        {canWrite && (
          <button type="button" className="btn primary cta" onClick={() => setEditor("create")}>
            {t.tools.addTool}
          </button>
        )}
      </div>

      <form className="toolbar" role="search" onSubmit={(event) => void handleScan(event)}>
        <input
          className="search-input"
          type="search"
          value={scanText}
          onChange={(event) => setScanText(event.target.value)}
          placeholder={t.tools.scanPlaceholder}
          aria-label={t.tools.scanLabel}
          autoFocus
        />
      </form>
      {scanMiss !== null && <div className="error-banner" role="alert">{scanMiss}</div>}
      {scanned !== null && (
        <ScannedToolCard
          tool={scanned}
          canEdit={canWrite}
          onClear={() => setScanned(null)}
          onEdit={() => setEditor(scanned)}
        />
      )}

      {!demo && canSync && (
        <div className="panel compact-panel">
          <div className="toolbar">
            <label className="control-label" htmlFor="tool-sync-institute">
              {t.tools.instituteLabel}
            </label>
            <select
              id="tool-sync-institute"
              className="select-input"
              value={selectedInstitute}
              disabled={user?.institute_code !== null && user?.institute_code !== undefined}
              onChange={(event) => setSelectedInstitute(event.target.value)}
            >
              {institutes.length === 0 ? (
                <option value="">{t.tools.noInstitutes}</option>
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
              onClick={() => void handleMirrorSync()}
            >
              {syncing ? t.common.loading : t.tools.syncFromMirror}
            </button>
          </div>
          {syncNotice !== null && <div className="info-banner" role="status">{syncNotice}</div>}
        </div>
      )}

      {editor !== null && (
        <ToolEditor
          tool={editor === "create" ? null : editor}
          kindOptions={kindOptions}
          onCancel={() => setEditor(null)}
          onSave={saveEditor}
          onDelete={editor === "create" || !isAdmin ? undefined : () => void removeTool(editor)}
        />
      )}

      <div className="toolbar tools-filters">
        <select
          className="select-input"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          aria-label={t.tools.kindLabel}
        >
          <option value="">{t.tools.allKinds}</option>
          {kindOptions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select
          className="select-input"
          value={fits}
          onChange={(event) => setFits(event.target.value)}
          aria-label={t.tools.fitsLabel}
        >
          <option value="">{t.tools.allTypes}</option>
          {typeOptions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select
          className="select-input"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          aria-label={t.tools.statusFilterLabel}
        >
          <option value="">{t.tools.allStatuses}</option>
          {STATUSES.map((value) => <option key={value} value={value}>{t.tools.statusLabel(value)}</option>)}
        </select>
        <span className="muted">{t.tools.hint}</span>
      </div>

      {error !== null ? (
        <div className="error-banner" role="alert">{t.tools.loadError}: {error}</div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : tools.length === 0 ? (
        <p className="state-note">{t.tools.empty}</p>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl tools-table">
            <thead>
              <tr>
                <th>{t.tools.colKind}</th><th>{t.tools.colCode}</th><th>{t.tools.colLabel}</th>
                <th>{t.tools.colRfid}</th><th>{t.tools.colFits}</th><th>{t.tools.colStatus}</th>
                {canWrite && <th className="right">{t.tools.colActions}</th>}
              </tr>
            </thead>
            <tbody>
              {tools.map((tool) => (
                <tr key={tool.id}>
                  <td>{tool.kind}</td><td className="mono">{tool.code}</td>
                  <td>{tool.label ?? t.common.none}</td>
                  <td className="mono muted">{tool.rfid ?? t.common.none}</td>
                  <td><div className="row-actions">{tool.compatible_types.map((value) => <span className="chip neutral" key={value}>{value}</span>)}</div></td>
                  <td><span className={statusChip(tool.status)}>{t.tools.statusLabel(tool.status)}</span></td>
                  {canWrite && (
                    <td className="acts">
                      <button className="btn sm" onClick={() => setEditor(tool)}>{t.tools.edit}</button>
                      {tool.status !== "active" && <button className="btn sm" disabled={busyToolId === tool.id} onClick={() => void changeStatus(tool, "active")}>{t.tools.activate}</button>}
                      {tool.status !== "flagged" && <button className="btn sm" disabled={busyToolId === tool.id} onClick={() => void changeStatus(tool, "flagged")}>{t.tools.flag}</button>}
                      {tool.status !== "blacklisted" && <button className="btn sm serious-action" disabled={busyToolId === tool.id} onClick={() => void changeStatus(tool, "blacklisted")}>{t.tools.blacklist}</button>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ToolEditor({
  tool,
  kindOptions,
  onCancel,
  onSave,
  onDelete,
}: {
  tool: Tool | null;
  kindOptions: string[];
  onCancel: () => void;
  onSave: (body: ToolCreateBody | ToolUpdateBody) => Promise<void>;
  onDelete?: () => void;
}) {
  const [kind, setKind] = useState(tool?.kind ?? "jig");
  const [code, setCode] = useState(tool?.code ?? "");
  const [label, setLabel] = useState(tool?.label ?? "");
  const [rfid, setRfid] = useState(tool?.rfid ?? "");
  const [types, setTypes] = useState((tool?.compatible_types ?? []).join(", "));
  const [status, setStatus] = useState<ToolStatus>(tool?.status ?? "active");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (kind.trim() === "" || code.trim() === "") {
      setError(t.tools.editorRequired);
      return;
    }
    setSaving(true);
    setError(null);
    const values = {
      kind: kind.trim(), code: code.trim(), label: label.trim() || null,
      rfid: rfid.trim() || null, compatible_types: normalizeTypes(types), status,
    };
    try {
      await onSave(values);
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="panel tool-editor" onSubmit={(event) => void submit(event)}>
      <div className="tool-editor-head">
        <div><h2>{tool === null ? t.tools.createTitle : t.tools.editTitle(tool.code)}</h2><p className="hint">{t.tools.editorHint}</p></div>
        <span className={statusChip(status)}>{t.tools.statusLabel(status)}</span>
      </div>
      <div className="tool-editor-grid">
        <label><span className="control-label">{t.tools.kindField}</span><input className="search-input" list="tool-kind-options" value={kind} onChange={(event) => setKind(event.target.value)} /></label>
        <datalist id="tool-kind-options">{kindOptions.map((value) => <option key={value} value={value} />)}</datalist>
        <label><span className="control-label">{t.tools.codeField}</span><input className="search-input mono" value={code} onChange={(event) => setCode(event.target.value)} /></label>
        <label><span className="control-label">{t.tools.labelField}</span><input className="search-input" value={label} onChange={(event) => setLabel(event.target.value)} /></label>
        <label><span className="control-label">{t.tools.rfidField}</span><input className="search-input mono" value={rfid} onChange={(event) => setRfid(event.target.value)} /></label>
        <label className="wide"><span className="control-label">{t.tools.compatibleTypesField}</span><input className="search-input mono" value={types} onChange={(event) => setTypes(event.target.value)} placeholder={t.tools.compatibleTypesPlaceholder} /></label>
        <label><span className="control-label">{t.tools.statusField}</span><select className="select-input" value={status} onChange={(event) => setStatus(event.target.value as ToolStatus)}>{STATUSES.map((value) => <option key={value} value={value}>{t.tools.statusLabel(value)}</option>)}</select></label>
      </div>
      {error !== null && <div className="error-banner" role="alert">{error}</div>}
      <div className="action-controls tool-editor-actions">
        {onDelete !== undefined && <button type="button" className="btn serious-action" onClick={onDelete}>{t.tools.delete}</button>}
        <span className="spacer" />
        <button type="button" className="btn" onClick={onCancel}>{t.common.cancel}</button>
        <button className="btn primary" disabled={saving}>{saving ? t.common.loading : t.tools.save}</button>
      </div>
    </form>
  );
}

function ScannedToolCard({
  tool, canEdit, onClear, onEdit,
}: {
  tool: Tool; canEdit: boolean; onClear: () => void; onEdit: () => void;
}) {
  return (
    <div className="panel scanned-tool" data-status={tool.status}>
      <div className="scanned-head">
        <span className="field-label">{t.tools.scanned}</span>
        <span className={statusChip(tool.status)}>{t.tools.statusLabel(tool.status)}</span>
        <span className="spacer" />
        {canEdit && <button type="button" className="btn" onClick={onEdit}>{t.tools.edit}</button>}
        <button type="button" className="btn" onClick={onClear}>{t.tools.scanClear}</button>
      </div>
      <div className="field-grid">
        <Field label={t.tools.scanKind} value={tool.kind} />
        <Field label={t.tools.scanCode} value={tool.code} mono />
        <Field label={t.tools.scanLabelText} value={tool.label ?? t.common.none} />
        <Field label={t.tools.scanRfid} value={tool.rfid ?? t.common.none} mono />
      </div>
      <div className="scanned-fits"><span className="field-label">{t.tools.scanFits}</span><div className="row-actions">{tool.compatible_types.map((value) => <span className="chip neutral" key={value}>{value}</span>)}</div></div>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div><div className="field-label">{label}</div><div className={mono ? "field-value mono" : "field-value"}>{value}</div></div>;
}
