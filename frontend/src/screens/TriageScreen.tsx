import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getIngestFiles, getIngestPreview } from "../api";
import type { IngestFile, IngestPreview } from "../api";
import { getDemoComponent, makeDemoIngestFiles } from "../demoData";
import { formatTimestamp, t } from "../i18n";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusChip(file: IngestFile): string {
  if (file.error !== null || file.status === "failed") return "chip red";
  if (file.status === "triage") return "chip amber";
  if (file.status === "proposed" || file.status === "processed") return "chip green";
  return "chip neutral";
}

function demoPreview(file: IngestFile): IngestPreview {
  const component = file.component_sn === null ? null : getDemoComponent(file.component_sn);
  const uploadReady = file.error === null && file.component_sn !== null && file.test_type !== null;
  return {
    file_id: file.id,
    parser: file.parser ?? t.triage.unknownParser,
    upload_ready: uploadReady,
    component_sn: file.component_sn,
    local_name: component?.local_name ?? null,
    component_mirrored: component !== null,
    component_stage: component?.stage ?? null,
    institute_code: component?.institute_code ?? null,
    test_type: file.test_type,
    run_number: null,
    institution: component?.institute_code ?? null,
    measured_at: null,
    passed: null,
    problems: file.error !== null,
    n_properties: 0,
    results: [],
    issues: file.error === null ? [] : [file.error],
    warnings: uploadReady ? [t.triage.demoPreviewWarning] : [],
  };
}

export default function TriageScreen({
  onOpenComponent,
}: {
  onOpenComponent: (sn: string) => void;
}) {
  const [files, setFiles] = useState<IngestFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [preview, setPreview] = useState<IngestPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewRequest = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setFiles(await getIngestFiles());
      setDemo(false);
    } catch (caught) {
      if (caught instanceof ApiError && caught.isNetwork) {
        setFiles(makeDemoIngestFiles());
        setDemo(true);
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => previewRequest.current?.abort(), []);

  async function handleTogglePreview(file: IngestFile) {
    previewRequest.current?.abort();
    previewRequest.current = null;
    if (previewId === file.id) {
      setPreviewId(null);
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }
    setPreviewId(file.id);
    setPreview(null);
    setPreviewError(null);
    if (demo) {
      setPreview(demoPreview(file));
      return;
    }
    const ctrl = new AbortController();
    previewRequest.current = ctrl;
    setPreviewLoading(true);
    try {
      const next = await getIngestPreview(file.id, ctrl.signal);
      if (!ctrl.signal.aborted) setPreview(next);
    } catch (caught) {
      if (!ctrl.signal.aborted) setPreviewError(errorMessage(caught));
    } finally {
      if (previewRequest.current === ctrl) {
        previewRequest.current = null;
        setPreviewLoading(false);
      }
    }
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.triage}</h1>
        <span className="sub">{t.triage.subtitle}</span>
        <span className="chip neutral">{t.triage.readOnly}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>
      {demo && (
        <div className="toolbar">
          <span className="muted">{t.common.demoNote}</span>
        </div>
      )}
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.triage.loadError}: {error}
          </span>
          <button type="button" className="btn" onClick={() => void load()}>
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : files.length === 0 ? (
        <p className="state-note">{t.triage.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table ingest-log-table">
            <thead>
              <tr>
                <th scope="col">{t.triage.colFile}</th>
                <th scope="col">{t.triage.colParser}</th>
                <th scope="col">{t.triage.colComponent}</th>
                <th scope="col">{t.triage.colStatus}</th>
                <th scope="col">{t.triage.colUploadedBy}</th>
                <th scope="col">{t.triage.colCreated}</th>
                <th scope="col">{t.triage.colError}</th>
                <th scope="col">{t.triage.colPreview}</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <Fragment key={file.id}>
                  <tr>
                    <td>
                      <div className="tree-row">
                        <strong>{file.filename}</strong>
                        <span className="mono muted">
                          #{file.id} · {file.sha256.slice(0, 10)} · {t.triage.fileSize(file.size_bytes)}
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="tree-row">
                        <span className="mono">{file.parser ?? t.triage.unknownParser}</span>
                        {file.test_type !== null && (
                          <span className="mono muted">{file.test_type}</span>
                        )}
                      </div>
                    </td>
                    <td>
                      {file.component_sn === null ? (
                        <span className="muted">{t.common.none}</span>
                      ) : (
                        <button
                          type="button"
                          className="link-btn mono"
                          onClick={() => onOpenComponent(file.component_sn as string)}
                        >
                          {file.component_sn}
                        </button>
                      )}
                    </td>
                    <td>
                      <span className={statusChip(file)}>{file.status}</span>
                    </td>
                    <td>{file.uploaded_by}</td>
                    <td className="muted">{formatTimestamp(file.created_at)}</td>
                    <td className={file.error === null ? "muted" : "error-text"}>
                      {file.error ?? t.common.none}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn"
                        aria-expanded={previewId === file.id}
                        onClick={() => void handleTogglePreview(file)}
                      >
                        {previewId === file.id ? t.triage.hidePreview : t.triage.preview}
                      </button>
                    </td>
                  </tr>
                  {previewId === file.id && (
                    <tr className="preview-row">
                      <td colSpan={8}>
                        {previewLoading ? (
                          <p className="state-note">{t.common.loading}</p>
                        ) : previewError !== null ? (
                          <p className="error-text">
                            {t.triage.previewFailed}: {previewError}
                          </p>
                        ) : preview !== null ? (
                          <PreviewPanel preview={preview} />
                        ) : null}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PreviewPanel({ preview }: { preview: IngestPreview }) {
  return (
    <div className="preview-panel">
      <div className="toolbar">
        <span className={preview.upload_ready ? "chip green" : "chip amber"}>
          {preview.upload_ready ? t.triage.previewUploadReady : t.triage.previewNotReady}
        </span>
        <span className="chip neutral mono">
          {t.triage.previewParser}: {preview.parser}
        </span>
        {preview.test_type !== null && <span className="chip stage">{preview.test_type}</span>}
        {preview.run_number !== null && (
          <span className="muted">
            {t.triage.previewRun} {preview.run_number}
          </span>
        )}
        {preview.measured_at !== null && (
          <span className="muted">
            {t.triage.previewMeasuredAt} {preview.measured_at}
          </span>
        )}
        {preview.passed !== null && (
          <span className={preview.passed ? "chip green" : "chip red"}>
            {t.triage.previewPassed}: {String(preview.passed)}
          </span>
        )}
        {preview.problems === true && <span className="chip amber">{t.triage.previewProblems}</span>}
      </div>
      <div className="toolbar">
        {preview.component_sn !== null && <span className="mono">{preview.component_sn}</span>}
        {preview.local_name !== null && preview.component_sn !== null && (
          <span className="muted">{t.triage.previewLocalName(preview.local_name)}</span>
        )}
        {preview.component_mirrored &&
        preview.component_stage !== null &&
        preview.institute_code !== null ? (
          <span className="muted">
            {t.triage.previewMirrored(preview.component_stage, preview.institute_code)}
          </span>
        ) : (
          <span className="muted">{t.triage.previewNotMirrored}</span>
        )}
      </div>
      {preview.issues.length > 0 && (
        <div>
          <div className="field-label">{t.triage.previewIssues}</div>
          <ul className="preview-list error-text">
            {preview.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
      {preview.warnings.length > 0 && (
        <div>
          <div className="field-label">{t.triage.previewWarnings}</div>
          <ul className="preview-list muted">
            {preview.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
      {preview.results.length > 0 && (
        <div>
          <div className="field-label">{t.triage.previewResults}</div>
          <table className="data-table preview-results">
            <tbody>
              {preview.results.map((result) => (
                <tr key={result.name}>
                  <td className="mono">{result.name}</td>
                  <td className="muted">{result.kind}</td>
                  <td className="mono">{result.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
