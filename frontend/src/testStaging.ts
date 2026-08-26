/**
 * Shared staging plumbing for test uploads (spec §H2).
 *
 * Every test entry point — the Add-test-result card and the worksheet's
 * in-row edit strip — stages a run through exactly one pipeline:
 *
 *   ingest (`POST /api/ingest/files`) → dry-run (`GET …/preview`) →
 *   propose-outbox (`POST …/propose-outbox`).
 *
 * The server owns validation: the dry-run reports blocking `issues`, and
 * propose-outbox answers 409 when issues remain or the file already has an
 * outbox action. The client-side guards (`stageBlockReason`, the hook's
 * `canStage`) mirror those rules only to keep the buttons honest; the server
 * remains the authority, so a 409 that slips through is surfaced verbatim.
 *
 * Two consumption styles are exported on purpose:
 *  - plain step functions (`ingestTestPayload` → `fetchDryRun` →
 *    `proposeStagedUpload`) for callers that manage their own state, and
 *  - the `useTestStaging` hook, which bundles the same three steps with
 *    busy/error state and stale-response (generation) guarding.
 */

import { useCallback, useRef, useState } from "react";

import {
  getIngestPreview,
  postIngestFile,
  postIngestOutboxProposal,
} from "./api";
import type {
  IngestFile,
  IngestFileCreate,
  IngestPreview,
  OutboxAction,
} from "./api";
import type { TestFormSubmitPayload } from "./TestForm";

/** The canonical manual-entry ingest body: an explicit allowlist so a new
 * `TestFormSubmitPayload` field never silently reaches the server unreviewed. */
export function manualEntryPayload(
  payload: TestFormSubmitPayload,
): Record<string, unknown> {
  return {
    component: payload.component,
    testType: payload.testType,
    runNumber: payload.runNumber,
    date: payload.date,
    passed: payload.passed,
    problems: payload.problems,
    properties: payload.properties,
    results: payload.results,
  };
}

// ---- Plain step functions ---------------------------------------------------

export type IngestTestPayloadOptions = {
  filename: string;
  payload: Record<string, unknown>;
  /** Server-side pin: a mismatching SN in the payload becomes a dry-run issue. */
  componentSn: string;
  /** Optional test-type pin, validated the same way. */
  testType?: string;
  /** Set for form entry; file drops keep the server-side parser detection. */
  parser?: "manual-entry";
};

/**
 * Step 1 — create the ingest file. Deliberately builds the body with
 * conditional spreads so absent options never appear as `undefined` keys
 * (the ingest contract carries no client actor fields either).
 */
export function ingestTestPayload(
  options: IngestTestPayloadOptions,
): Promise<IngestFile> {
  const body: IngestFileCreate = {
    filename: options.filename,
    payload: options.payload,
    component_sn: options.componentSn,
    ...(options.testType === undefined ? {} : { test_type: options.testType }),
    ...(options.parser === undefined ? {} : { parser: options.parser }),
  };
  return postIngestFile(body);
}

/** Step 2 — the server dry-run for an ingest file. */
export function fetchDryRun(
  fileId: number,
  signal?: AbortSignal,
): Promise<IngestPreview> {
  // No explicit `undefined` passthrough — call sites and tests treat the
  // one-argument form as the canonical request shape.
  return signal === undefined
    ? getIngestPreview(fileId)
    : getIngestPreview(fileId, signal);
}

export type StageBlockReason =
  | "no_preview"
  | "already_staged"
  | "issues"
  | "not_ready";

/**
 * Client-side mirror of the propose-outbox 409 rules. `null` means staging
 * may be attempted. `existingActionId` is the already-known outbox action for
 * this ingest file (local state or `IngestFile.outbox_action_id`).
 */
export function stageBlockReason(
  preview: IngestPreview | null,
  existingActionId: number | null,
): StageBlockReason | null {
  if (preview === null) return "no_preview";
  if (existingActionId !== null) return "already_staged";
  if (preview.issues.length > 0) return "issues";
  if (!preview.upload_ready) return "not_ready";
  return null;
}

/**
 * Step 3 — propose the outbox draft (the "Stage" action). Throws the
 * `ApiError` unchanged; a 409 carries the server's reason in its message.
 */
export function proposeStagedUpload(
  fileId: number,
  instituteCode?: string,
): Promise<OutboxAction> {
  const body: Parameters<typeof postIngestOutboxProposal>[1] = {
    ...(instituteCode === undefined ? {} : { institute_code: instituteCode }),
  };
  return postIngestOutboxProposal(fileId, body);
}

/**
 * Human-readable message for a failed staging step. Prefers the FastAPI
 * `detail` when present (duck-typed rather than `instanceof ApiError` so it
 * stays robust under partially mocked api modules in tests).
 */
export function stagingErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail !== "") return detail;
    return error.message;
  }
  return String(error);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ---- Hook variant -----------------------------------------------------------
//
// Same pipeline with busy/error state and stale-response (generation)
// guarding. UI-agnostic: it never decides on its own when to call
// `stageUpload` — callers choose (AddTestResult waits for an explicit
// "Stage upload" click; the worksheet's edit strip chains straight into it
// after a clean preview).

export type TestStagingBusy = "ingest" | "preview" | "stage" | null;

export type TestStagingLabels = {
  ingestFailed: (error: string) => string;
  previewFailed: (error: string) => string;
  stageFailed: (error: string) => string;
};

export type IngestPayloadOptions = {
  componentSn: string;
  testType?: string;
  parser?: "manual-entry";
  /** Reuse a generation an earlier async step already began (e.g. reading a
   * dropped file) so a stale response from either step is dropped together. */
  generation?: number;
};

export type StageUploadOptions = {
  instituteCode?: string;
};

export type StageUploadResult = {
  action: OutboxAction;
  ingest: IngestFile;
  preview: IngestPreview;
  /** The generation the propose-outbox call ran under. Pass to
   * `operationIsCurrent` to guard work that runs after `stageUpload` resolves
   * (e.g. before triggering a parent refresh). */
  generation: number;
};

export type UseTestStagingOptions = {
  labels: TestStagingLabels;
  onPreviewReady?: (file: IngestFile, preview: IngestPreview) => void | Promise<unknown>;
};

export type UseTestStagingResult = {
  busy: TestStagingBusy;
  ingest: IngestFile | null;
  preview: IngestPreview | null;
  entryError: string | null;
  previewError: string | null;
  stageError: string | null;
  stagedActionId: number | null;
  /** True once a clean, not-yet-staged preview exists. */
  canStage: boolean;
  beginOperation: () => number;
  operationIsCurrent: (generation: number) => boolean;
  /** Client-side busy/error setters for steps that happen before the ingest
   * call itself (e.g. reading a dropped file). */
  setBusy: (value: TestStagingBusy) => void;
  setEntryError: (message: string | null) => void;
  ingestPayload: (
    filename: string,
    payload: Record<string, unknown>,
    options: IngestPayloadOptions,
  ) => Promise<IngestFile | null>;
  refreshPreview: () => Promise<void>;
  stageUpload: (options?: StageUploadOptions) => Promise<StageUploadResult | null>;
  reset: () => void;
};

type State = {
  busy: TestStagingBusy;
  ingest: IngestFile | null;
  preview: IngestPreview | null;
  entryError: string | null;
  previewError: string | null;
  stageError: string | null;
  stagedActionId: number | null;
};

const INITIAL_STATE: State = {
  busy: null,
  ingest: null,
  preview: null,
  entryError: null,
  previewError: null,
  stageError: null,
  stagedActionId: null,
};

export function useTestStaging(options: UseTestStagingOptions): UseTestStagingResult {
  const labelsRef = useRef(options.labels);
  labelsRef.current = options.labels;
  const onPreviewReadyRef = useRef(options.onPreviewReady);
  onPreviewReadyRef.current = options.onPreviewReady;

  const [state, setState] = useState<State>(INITIAL_STATE);
  // Imperative snapshot of the pipeline results, updated the moment a value
  // is known (not on re-render): a caller that chains
  // `await ingestPayload(...); await stageUpload()` inside one event handler
  // must not lose the race against React's state flush.
  const latestRef = useRef<{
    ingest: IngestFile | null;
    preview: IngestPreview | null;
    stagedActionId: number | null;
  }>({ ingest: null, preview: null, stagedActionId: null });
  const generationRef = useRef(0);

  const beginOperation = useCallback((): number => {
    generationRef.current += 1;
    return generationRef.current;
  }, []);
  const operationIsCurrent = useCallback(
    (generation: number): boolean => generation === generationRef.current,
    [],
  );

  const setBusy = useCallback((value: TestStagingBusy) => {
    setState((current) => ({ ...current, busy: value }));
  }, []);
  const setEntryError = useCallback((message: string | null) => {
    setState((current) => ({ ...current, entryError: message }));
  }, []);

  const reset = useCallback(() => {
    beginOperation();
    latestRef.current = { ingest: null, preview: null, stagedActionId: null };
    setState(INITIAL_STATE);
  }, [beginOperation]);

  async function notifyPreviewReady(file: IngestFile, preview: IngestPreview) {
    try {
      await onPreviewReadyRef.current?.(file, preview);
    } catch {
      // A parent refresh failure must not turn a successful ingest into a false failure.
    }
  }

  const ingestPayload = useCallback(
    async (
      filename: string,
      payload: Record<string, unknown>,
      ingestOptions: IngestPayloadOptions,
    ): Promise<IngestFile | null> => {
      const generation = ingestOptions.generation ?? beginOperation();
      latestRef.current = { ingest: null, preview: null, stagedActionId: null };
      setState((current) => ({
        ...current,
        busy: "ingest",
        entryError: null,
        previewError: null,
        stageError: null,
        ingest: null,
        preview: null,
        stagedActionId: null,
      }));

      let created: IngestFile | null = null;
      try {
        created = await ingestTestPayload({
          filename,
          payload,
          componentSn: ingestOptions.componentSn,
          ...(ingestOptions.testType === undefined
            ? {}
            : { testType: ingestOptions.testType }),
          ...(ingestOptions.parser === undefined
            ? {}
            : { parser: ingestOptions.parser }),
        });
        if (!operationIsCurrent(generation)) return null;
        latestRef.current = { ...latestRef.current, ingest: created };
        setState((current) => ({ ...current, ingest: created }));

        const nextPreview = await fetchDryRun(created.id);
        if (!operationIsCurrent(generation)) return null;
        latestRef.current = {
          ingest: created,
          preview: nextPreview,
          stagedActionId: created.outbox_action_id,
        };
        setState((current) => ({
          ...current,
          preview: nextPreview,
          stagedActionId: created?.outbox_action_id ?? null,
        }));
        await notifyPreviewReady(created, nextPreview);
        return created;
      } catch (error) {
        if (!operationIsCurrent(generation)) return null;
        const message = errorMessage(error);
        setState((current) =>
          created === null
            ? { ...current, entryError: labelsRef.current.ingestFailed(message) }
            : { ...current, previewError: labelsRef.current.previewFailed(message) },
        );
        return null;
      } finally {
        if (operationIsCurrent(generation)) {
          setState((current) => ({ ...current, busy: null }));
        }
      }
    },
    [beginOperation, operationIsCurrent],
  );

  const refreshPreview = useCallback(async () => {
    const current = latestRef.current.ingest;
    if (current === null) return;
    const generation = beginOperation();
    setState((s) => ({ ...s, busy: "preview", previewError: null }));
    try {
      const nextPreview = await fetchDryRun(current.id);
      if (!operationIsCurrent(generation)) return;
      latestRef.current = { ...latestRef.current, preview: nextPreview };
      setState((s) => ({ ...s, preview: nextPreview }));
      await notifyPreviewReady(current, nextPreview);
    } catch (error) {
      if (operationIsCurrent(generation)) {
        setState((s) => ({
          ...s,
          previewError: labelsRef.current.previewFailed(errorMessage(error)),
        }));
      }
    } finally {
      if (operationIsCurrent(generation)) setState((s) => ({ ...s, busy: null }));
    }
  }, [beginOperation, operationIsCurrent]);

  const stageUpload = useCallback(
    async (stageOptions: StageUploadOptions = {}): Promise<StageUploadResult | null> => {
      const snapshotIngest = latestRef.current.ingest;
      const snapshotPreview = latestRef.current.preview;
      if (
        snapshotIngest === null ||
        stageBlockReason(
          snapshotPreview,
          latestRef.current.stagedActionId ?? snapshotIngest.outbox_action_id,
        ) !== null ||
        snapshotPreview === null
      ) {
        return null;
      }
      const generation = beginOperation();
      setState((s) => ({ ...s, busy: "stage", stageError: null }));
      try {
        const action = await proposeStagedUpload(
          snapshotIngest.id,
          stageOptions.instituteCode,
        );
        if (!operationIsCurrent(generation)) return null;
        const nextIngest: IngestFile = {
          ...snapshotIngest,
          status: "proposed",
          outbox_action_id: action.id,
        };
        latestRef.current = {
          ingest: nextIngest,
          preview: snapshotPreview,
          stagedActionId: action.id,
        };
        setState((s) => ({ ...s, ingest: nextIngest, stagedActionId: action.id }));
        return { action, ingest: nextIngest, preview: snapshotPreview, generation };
      } catch (error) {
        if (operationIsCurrent(generation)) {
          setState((s) => ({
            ...s,
            stageError: labelsRef.current.stageFailed(stagingErrorMessage(error)),
          }));
        }
        return null;
      } finally {
        if (operationIsCurrent(generation)) setState((s) => ({ ...s, busy: null }));
      }
    },
    [beginOperation, operationIsCurrent],
  );

  const canStage =
    state.ingest !== null &&
    stageBlockReason(
      state.preview,
      state.stagedActionId ?? state.ingest.outbox_action_id,
    ) === null;

  return {
    ...state,
    canStage,
    beginOperation,
    operationIsCurrent,
    setBusy,
    setEntryError,
    ingestPayload,
    refreshPreview,
    stageUpload,
    reset,
  };
}
