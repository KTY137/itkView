import { useEffect, useState } from "react";
import { ApiError, getTools } from "../api";
import type { Tool } from "../api";
import { filterDemoTools } from "../demoData";
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
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [kind, setKind] = useState("");
  const [fits, setFits] = useState("");

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
  }, [kind, fits]);

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.tools}</h1>
        <span className="sub">{t.tools.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>
      <div className="toolbar">
        <select
          className="select-input"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          aria-label={t.tools.kindLabel}
        >
          <option value="">{t.tools.allKinds}</option>
          {KINDS.map((k) => (
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
          {MODULE_TYPES.map((m) => (
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
