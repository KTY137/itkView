import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IngestFile, IngestPreview, OutboxAction } from "./api";
import { getIngestPreview, postIngestFile, postIngestOutboxProposal } from "./api";
import {
  manualEntryPayload,
  stageBlockReason,
  useTestStaging,
} from "./testStaging";
import type { StageUploadResult } from "./testStaging";
import type { TestFormSubmitPayload } from "./TestForm";

vi.mock("./api", () => ({
  getIngestPreview: vi.fn(),
  postIngestFile: vi.fn(),
  postIngestOutboxProposal: vi.fn(),
}));

const labels = {
  ingestFailed: (error: string) => `Ingest failed: ${error}`,
  previewFailed: (error: string) => `Preview failed: ${error}`,
  stageFailed: (error: string) => `Stage failed: ${error}`,
};

const manualPayload: TestFormSubmitPayload = {
  component: "20USEM00000001",
  testType: "GLUE_WEIGHT",
  runNumber: "4",
  date: "2026-08-26T10:00:00.000Z",
  passed: true,
  problems: false,
  properties: { JIG: "JIG-1" },
  results: { GW1: 0.12 },
};

const ingestFile: IngestFile = {
  id: 71,
  filename: "GLUE_WEIGHT-manual.json",
  sha256: "a".repeat(64),
  size_bytes: 40,
  status: "processed",
  component_sn: "20USEM00000001",
  test_type: "GLUE_WEIGHT",
  parser: "manual-entry",
  error: null,
  outbox_action_id: null,
  uploaded_by: "server-attributed@example.org",
  created_at: "2026-08-26T10:00:00Z",
  updated_at: "2026-08-26T10:00:00Z",
};

const cleanPreview: IngestPreview = {
  file_id: 71,
  parser: "manual-entry",
  upload_ready: true,
  component_sn: "20USEM00000001",
  local_name: null,
  component_mirrored: true,
  component_stage: "GLUED",
  institute_code: "EXAMPLE",
  test_type: "GLUE_WEIGHT",
  run_number: "4",
  institution: "EXAMPLE",
  measured_at: "2026-08-26T09:55:00Z",
  passed: true,
  problems: false,
  n_properties: 1,
  results: [{ name: "GW1", kind: "scalar", value: "0.12" }],
  issues: [],
  warnings: [],
};

const action: OutboxAction = {
  id: 92,
  institute_id: 3,
  kind: "upload_test_run",
  payload: { ingest_file_id: 71 },
  status: "draft",
  error: null,
  attempts: 0,
  external_ref: null,
  created_by: "server-attributed@example.org",
  created_at: "2026-08-26T10:01:00Z",
  updated_at: "2026-08-26T10:01:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("manualEntryPayload", () => {
  it("extracts exactly the allow-listed fields, nothing else", () => {
    const payload = manualEntryPayload(manualPayload);
    expect(payload).toEqual({
      component: "20USEM00000001",
      testType: "GLUE_WEIGHT",
      runNumber: "4",
      date: "2026-08-26T10:00:00.000Z",
      passed: true,
      problems: false,
      properties: { JIG: "JIG-1" },
      results: { GW1: 0.12 },
    });
  });
});

describe("stageBlockReason", () => {
  it("blocks when there is no preview yet", () => {
    expect(stageBlockReason(null, null)).toBe("no_preview");
  });
  it("blocks when the file is already staged", () => {
    expect(stageBlockReason(cleanPreview, 5)).toBe("already_staged");
  });
  it("blocks on dry-run issues", () => {
    expect(stageBlockReason({ ...cleanPreview, issues: ["bad"] }, null)).toBe("issues");
  });
  it("blocks when the server marks the preview not ready", () => {
    expect(stageBlockReason({ ...cleanPreview, upload_ready: false }, null)).toBe("not_ready");
  });
  it("allows a clean, unstaged preview", () => {
    expect(stageBlockReason(cleanPreview, null)).toBeNull();
  });
});

describe("useTestStaging", () => {
  beforeEach(() => {
    vi.mocked(postIngestFile).mockResolvedValue(ingestFile);
    vi.mocked(getIngestPreview).mockResolvedValue(cleanPreview);
    vi.mocked(postIngestOutboxProposal).mockResolvedValue(action);
  });

  it("ingests, previews, and reports canStage once the dry-run is clean", async () => {
    const { result } = renderHook(() => useTestStaging({ labels }));

    await act(async () => {
      await result.current.ingestPayload("manual.json", { a: 1 }, { componentSn: "20USEM00000001" });
    });

    expect(postIngestFile).toHaveBeenCalledWith({
      filename: "manual.json",
      payload: { a: 1 },
      component_sn: "20USEM00000001",
    });
    expect(getIngestPreview).toHaveBeenCalledWith(71);
    expect(result.current.ingest).toEqual(ingestFile);
    expect(result.current.preview).toEqual(cleanPreview);
    expect(result.current.entryError).toBeNull();
    expect(result.current.canStage).toBe(true);
  });

  it("classifies a failed ingest as an entry error, not a preview error", async () => {
    vi.mocked(postIngestFile).mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useTestStaging({ labels }));

    await act(async () => {
      await result.current.ingestPayload("manual.json", {}, { componentSn: "20USEM00000001" });
    });

    expect(result.current.entryError).toBe("Ingest failed: boom");
    expect(result.current.previewError).toBeNull();
    expect(result.current.busy).toBeNull();
  });

  it("classifies a failed dry-run fetch as a preview error", async () => {
    vi.mocked(getIngestPreview).mockRejectedValueOnce(new Error("network down"));
    const { result } = renderHook(() => useTestStaging({ labels }));

    await act(async () => {
      await result.current.ingestPayload("manual.json", {}, { componentSn: "20USEM00000001" });
    });

    expect(result.current.entryError).toBeNull();
    expect(result.current.previewError).toBe("Preview failed: network down");
  });

  it("drops a stale ingest response once reset() bumps the generation", async () => {
    const pending = deferred<IngestFile>();
    vi.mocked(postIngestFile).mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useTestStaging({ labels }));

    let ingestPromise!: Promise<IngestFile | null>;
    act(() => {
      ingestPromise = result.current.ingestPayload("manual.json", {}, {
        componentSn: "20USEM00000001",
      });
    });

    act(() => {
      result.current.reset();
    });

    await act(async () => {
      pending.resolve(ingestFile);
      await ingestPromise;
    });

    // The stale response never reached the preview fetch or the state.
    expect(getIngestPreview).not.toHaveBeenCalled();
    expect(result.current.ingest).toBeNull();
    expect(result.current.entryError).toBeNull();
  });

  it("stages a clean preview and reports the generation for a post-stage guard", async () => {
    const { result } = renderHook(() => useTestStaging({ labels }));

    await act(async () => {
      await result.current.ingestPayload("manual.json", {}, { componentSn: "20USEM00000001" });
    });

    // Declared, not initialised: an initialiser would narrow the type to null
    // and TypeScript does not track the assignment inside act()'s callback.
    let stageResult!: StageUploadResult | null;
    await act(async () => {
      stageResult = await result.current.stageUpload({ instituteCode: "EXAMPLE" });
    });

    expect(postIngestOutboxProposal).toHaveBeenCalledWith(71, { institute_code: "EXAMPLE" });
    expect(stageResult).not.toBeNull();
    expect(stageResult?.action).toEqual(action);
    expect(result.current.operationIsCurrent(stageResult?.generation ?? -1)).toBe(true);
    expect(result.current.stagedActionId).toBe(92);
    expect(result.current.canStage).toBe(false);
  });

  it("refuses to stage when the dry-run has blocking issues", async () => {
    vi.mocked(getIngestPreview).mockResolvedValueOnce({ ...cleanPreview, issues: ["bad row"] });
    const { result } = renderHook(() => useTestStaging({ labels }));

    await act(async () => {
      await result.current.ingestPayload("manual.json", {}, { componentSn: "20USEM00000001" });
    });

    let stageResult: StageUploadResult | null = null;
    await act(async () => {
      stageResult = await result.current.stageUpload();
    });

    expect(postIngestOutboxProposal).not.toHaveBeenCalled();
    expect(stageResult).toBeNull();
  });

  it("surfaces a propose-outbox failure as a stage error", async () => {
    vi.mocked(postIngestOutboxProposal).mockRejectedValueOnce(new Error("conflict"));
    const { result } = renderHook(() => useTestStaging({ labels }));

    await act(async () => {
      await result.current.ingestPayload("manual.json", {}, { componentSn: "20USEM00000001" });
    });
    await act(async () => {
      await result.current.stageUpload();
    });

    await waitFor(() => expect(result.current.stageError).toBe("Stage failed: conflict"));
  });
});
