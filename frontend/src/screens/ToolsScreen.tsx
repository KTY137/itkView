import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, getInstitutes, getTools, postToolSync, scanTool } from "../api";
import type { Institute, Tool } from "../api";
import { useAuth } from "../auth";
import { filterDemoTools, scanDemoTool } from "../demoData";
import { t } from "../i18n";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// Common module types for the quick-select. Institute-agnostic seed list; the
// real set comes from the mirrored component types.
const MODULE_TYPES = ["R0", "R1", "R2", "R3M0", "R3M1", "R5M0", "R5M1"];
const KINDS = ["jig", "pickup_tool", "panel"];

function statusChip(status: string): string {
  if (status === "active") return "chip green";
  if (status === "flagged") return "chip amber";
  if (status === "blacklisted") return "chip red";
  return "chip neutral";
}

/**
 * Tool/jig registry with a type-filtered quick-select: pick a module type and
 * only the jigs/tools that fit it remain — the behaviour the assembly wizard
 * will reuse so operators never type a jig by hand (docs/07).
 */
export default function ToolsScreen() {
  const { canWrite } = useAuth();
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [kind, setKind] = useState("");
  const [fits, setFits] = useState("");
  const [scanText, setScanText] = useState("");
  const [scanned, setScanned] = useState<Tool | null>(null);
  const [scanMiss, setScanMiss] = useState<string | null>(null);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [selectedInstitute, setSelectedInstitute] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    getInstitutes(ctrl.signal)
      .then((data) => {
        setInstitutes(data);
        setSelectedInstitute((current) => {
          if (current !== "" && data.some((i) => i.code === current)) return current;
          return data[0]?.code ?? "";
        });
      })
      .catch(() => setInstitutes([]));
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    getTools({ kind: kind || undefined, fits: fits || undefined }, ctrl.signal)
      .then((data) => {
        setTools(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setTools(filterDemoTools(kind, fits));
          setDemo(true);
        } else {
          setError(errorMessage(err));
        }
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [kind, fits, reloadKey]);

  async function handleScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = scanText.trim();
    if (code === "") return;
    setScanMiss(null);
    try {
      const tool = await scanTool(code);
      setScanned(tool);
      setScanText("");
    } catch (err) {
      if (err instanceof ApiError && err.isNetwork) {
        const hit = scanDemoTool(code);
        if (hit) {
          setScanned(hit);
          setScanText("");
          return;
        }
      }
      setScanned(null);
      setScanMiss(t.tools.scanNotFound(code));
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
      setReloadKey((key) => key + 1);
    } catch (err) {
      setSyncNotice(`${t.tools.syncFailed}: ${errorMessage(err)}`);
    } finally {
      setSyncing(false);
    }
  }

  const kindOptions = [...new Set([...KINDS, ...tools.map((tool) => tool.kind)])].sort();
  const typeOptions = [
    ...new Set([...MODULE_TYPES, ...tools.flatMap((tool) => tool.compatible_types)]),
  ].sort();

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.tools}</h1>
        <span className="sub">{t.tools.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>
      <form className="toolbar" role="search" onSubmit={(e) => void handleScan(e)}>
        <input
          className="search-input"
          type="search"
          value={scanText}
          onChange={(e) => setScanText(e.target.value)}
          placeholder={t.tools.scanPlaceholder}
          aria-label={t.tools.scanLabel}
          autoFocus
        />
      </form>
      {scanMiss !== null && (
        <div className="info-banner" role="status">
          <span>{scanMiss}</span>
          <button type="button" className="btn" onClick={() => setScanMiss(null)}>
            OK
          </button>
        </div>
      )}
      {scanned !== null && <ScannedToolCard tool={scanned} onClear={() => setScanned(null)} />}
      {!demo && canWrite && (
        <div className="panel compact-panel">
          <div className="toolbar">
            <label className="control-label" htmlFor="tool-sync-institute">
              {t.tools.instituteLabel}
            </label>
            <select
              id="tool-sync-institute"
              className="select-input"
              value={selectedInstitute}
              onChange={(e) => setSelectedInstitute(e.target.value)}
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
          {syncNotice !== null && (
            <div className="info-banner" role="status">
              <span>{syncNotice}</span>
              <button type="button" className="btn" onClick={() => setSyncNotice(null)}>
                OK
              </button>
            </div>
          )}
        </div>
      )}
      <div className="toolbar">
        <select
          className="select-input"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          aria-label={t.tools.kindLabel}
        >
          <option value="">{t.tools.allKinds}</option>
          {kindOptions.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <select
          className="select-input"
          value={fits}
          onChange={(e) => setFits(e.target.value)}
          aria-label={t.tools.fitsLabel}
        >
          <option value="">{t.tools.allTypes}</option>
          {typeOptions.map((m) => (
            <option key={m} value={m}>
              {t.tools.fitsLabel}: {m}
            </option>
          ))}
        </select>
        <span className="muted">{t.tools.hint}</span>
      </div>
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.tools.loadError}: {error}
          </span>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : tools.length === 0 ? (
        <p className="state-note">{t.tools.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.tools.colKind}</th>
                <th scope="col">{t.tools.colCode}</th>
                <th scope="col">{t.tools.colLabel}</th>
                <th scope="col">{t.tools.colRfid}</th>
                <th scope="col">{t.tools.colFits}</th>
                <th scope="col">{t.tools.colStatus}</th>
              </tr>
            </thead>
            <tbody>
              {tools.map((tool) => (
                <tr key={tool.id}>
                  <td>{tool.kind}</td>
                  <td className="mono">{tool.code}</td>
                  <td>{tool.label ?? t.common.none}</td>
                  <td className="mono muted">{tool.rfid ?? t.common.none}</td>
                  <td>
                    <div className="row-actions">
                      {tool.compatible_types.map((type) => (
                        <span className="chip neutral" key={type}>
                          {type}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <span className={statusChip(tool.status)}>{tool.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Auto-pulled detail for a scanned jig/tool — the info that appears the moment
 * a tag is scanned, so an operator confirms the right jig without typing. */
function ScannedToolCard({ tool, onClear }: { tool: Tool; onClear: () => void }) {
  return (
    <div className="panel scanned-tool" data-status={tool.status}>
      <div className="scanned-head">
        <span className="field-label">{t.tools.scanned}</span>
        <span className={statusChip(tool.status)}>{tool.status}</span>
        <button type="button" className="btn" onClick={onClear}>
          {t.tools.scanClear}
        </button>
      </div>
      <div className="field-grid">
        <Field label={t.tools.scanKind} value={tool.kind} />
        <Field label={t.tools.scanCode} value={tool.code} mono />
        <Field label={t.tools.scanLabelText} value={tool.label ?? t.common.none} />
        <Field label={t.tools.scanRfid} value={tool.rfid ?? t.common.none} mono />
        <Field label={t.tools.scanStatus} value={tool.status} />
      </div>
      <div className="scanned-fits">
        <span className="field-label">{t.tools.scanFits}</span>
        <div className="row-actions">
          {tool.compatible_types.length === 0 ? (
            <span className="muted">{t.common.none}</span>
          ) : (
            tool.compatible_types.map((type) => (
              <span className="chip neutral" key={type}>
                {type}
              </span>
            ))
          )}
        </div>
      </div>
    </div>
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
