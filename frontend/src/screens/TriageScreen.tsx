import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  getIngestFiles,
  getIngestPreview,
  postIngestFile,
  postIngestOutboxProposal,
} from "../api";
import type { IngestFile, IngestPreview } from "../api";
import { makeDemoIngestFiles } from "../demoData";
import { formatTimestamp, t } from "../i18n";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function parseJsonObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(t.triage.invalidJson);
  }
  return parsed as Record<string, unknown>;
}

export default function TriageScreen() {
  const [files, setFiles] = useState<IngestFile[]>([]);
  const [filename, setFilename] = useState("");
  const [uploadedBy, setUploadedBy] = useState("ui-demo-user");
  const [payloadText, setPayloadText] = useState(t.triage.payloadPlaceholder);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busyProposalId, setBusyProposalId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const demoStore = useRef<IngestFile[] | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [preview, setPreview] = useState<IngestPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getIngestFiles();
      setFiles(data);
      setDemo(false);
    } catch (err) {
      if (err instanceof ApiError && err.isNetwork) {
        if (demoStore.current === null) demoStore.current = makeDemoIngestFiles();
        setFiles(demoStore.current);
        setDemo(true);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(null);
    setError(null);
    let payload: Record<string, unknown>;
    try {
      payload = parseJsonObject(payloadText);
    } catch (err) {
      setError(errorMessage(err));
      return;
    }

    setUploading(true);
    try {
      const created = await postIngestFile({
        filename: filename.trim(),
        uploaded_by: uploadedBy.trim(),
        payload,
      });
      setFiles((current) => [created, ...current]);
      setNotice(t.triage.uploadReceived(created.id, created.status));
      setFilename("");
    } catch (err) {
      if (err instanceof ApiError && err.isNetwork && demoStore.current !== null) {
        setNotice(t.outbox.transitionNetwork);
      } else {
        setError(`${t.triage.uploadFailed}: ${errorMessage(err)}`);
      }
    } finally {
      setUploading(false);
    }
  }

  async function handlePropose(file: IngestFile) {
    setNotice(null);
    setError(null);
    if (demo) {
      setNotice(t.outbox.transitionNetwork);
      return;
    }
    setBusyProposalId(file.id);
    try {
      const action = await postIngestOutboxProposal(file.id, { created_by: uploadedBy.trim() });
      setFiles((current) =>
        current.map((item) =>
          item.id === file.id
            ? { ...item, status: "proposed", error: null, outbox_action_id: action.id }
            : item,
        ),
      );
      setNotice(t.triage.proposedOutbox(action.id));
    } catch (err) {
      setError(`${t.triage.proposalFailed}: ${errorMessage(err)}`);
    } finally {
      setBusyProposalId(null);
    }
  }

  async function handleTogglePreview(file: IngestFile) {
    if (previewId === file.id) {
      setPreviewId(null);
      setPreview(null);
      return;
    }
    if (demo) {
      setNotice(t.triage.previewUnavailableDemo);
      return;
    }
    setPreviewId(file.id);
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      setPreview(await getIngestPreview(file.id));
    } catch (err) {
      setPreviewError(errorMessage(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.triage}</h1>
        <span className="sub">{t.triage.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>
      {demo && (
        <div className="toolbar">
          <span className="muted">{t.common.demoNote}</span>
        </div>
      )}
      <form className="panel compact-panel triage-form" onSubmit={handleUpload}>
        <div className="toolbar">
          <input
            className="text-input"
            value={filename}
            onChange={(event) => setFilename(event.target.value)}
            placeholder={t.triage.filenamePlaceholder}
            aria-label={t.triage.filenameLabel}
            maxLength={240}
            required
          />
          <input
            className="text-input"
            value={uploadedBy}
            onChange={(event) => setUploadedBy(event.target.value)}
            placeholder={t.triage.uploadedByPlaceholder}
            aria-label={t.triage.uploadedByLabel}
            maxLength={120}
            required
          />
          <button className="btn" disabled={uploading}>
            {uploading ? t.common.loading : t.triage.submit}
          </button>
        </div>
        <textarea
          className="json-input mono"
          value={payloadText}
          onChange={(event) => setPayloadText(event.target.value)}
          aria-label={t.triage.payloadLabel}
          rows={7}
          required
        />
      </form>
      {notice !== null && (
        <div className="info-banner" role="status">
          <span>{notice}</span>
          <button className="btn" onClick={() => setNotice(null)}>
            OK
          </button>
        </div>
      )}
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.triage.loadError}: {error}
          </span>
          <button className="btn" onClick={() => void load()}>
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : files.length === 0 ? (
        <p className="state-note">{t.triage.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.triage.colId}</th>
                <th scope="col">{t.triage.colFile}</th>
                <th scope="col">{t.triage.colStatus}</th>
                <th scope="col">{t.triage.colComponent}</th>
                <th scope="col">{t.triage.colTestType}</th>
                <th scope="col">{t.triage.colUploadedBy}</th>
                <th scope="col">{t.triage.colCreated}</th>
                <th scope="col">{t.triage.colError}</th>
                <th scope="col">{t.triage.colActions}</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <Fragment key={file.id}>
                <tr>
                  <td className="mono">#{file.id}</td>
                  <td>
                    <div className="tree-row">
                      <span>{file.filename}</span>
                      <span className="mono muted">{file.sha256.slice(0, 10)}</span>
                    </div>
                  </td>
                  <td>
                    <span className={file.status === "triage" ? "chip amber" : "chip green"}>
                      {file.status}
                    </span>
                  </td>
                  <td className="mono">{file.component_sn ?? t.common.none}</td>
                  <td className="mono">{file.test_type ?? t.common.none}</td>
                  <td>{file.uploaded_by}</td>
                  <td className="muted">{formatTimestamp(file.created_at)}</td>
                  <td className="error-text">{file.error ?? t.common.none}</td>
                  <td>
                    <div className="row-actions">
                      <button className="btn" onClick={() => void handleTogglePreview(file)}>
                        {previewId === file.id ? t.triage.hidePreview : t.triage.preview}
                      </button>
                      {file.outbox_action_id !== null ? (
                        <span className="chip neutral">
                          {t.triage.alreadyProposed(file.outbox_action_id)}
                        </span>
                      ) : file.component_sn === null || file.test_type === null ? (
                        <span className="muted">{t.triage.cannotPropose}</span>
                      ) : (
                        <button
                          className="btn"
                          disabled={busyProposalId === file.id}
                          onClick={() => void handlePropose(file)}
                        >
                          {busyProposalId === file.id ? t.common.loading : t.triage.proposeOutbox}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
                {previewId === file.id && (
                  <tr className="preview-row">
                    <td colSpan={9}>
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
