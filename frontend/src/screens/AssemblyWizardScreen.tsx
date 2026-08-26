import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  getGlueBatches,
  getInstitutes,
  getTools,
  postAssemblyAction,
  postAssemblyPreview,
  scanAssemblyComponent,
  scanGlueBatch,
  scanTool,
} from "../api";
import type {
  AssemblyDraft,
  AssemblyPreview,
  AssemblyToolSlot,
  ComponentOut,
  GlueBatch,
  OutboxAction,
  Tool,
} from "../api";
import { useAuth } from "../auth";
import {
  makeDemoAssemblyPreview,
  makeDemoGlueBatches,
  makeDemoTools,
  scanDemoComponent,
  scanDemoTool,
  stageDemoAssemblyAction,
} from "../demoData";
import { formatDuration, t } from "../i18n";
import { describeComponent, stageLabel } from "../ui";

type ScanRole = "parent" | "child";
type ResourceScanRole = "tool" | "glue";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function componentName(component: ComponentOut): string {
  return component.local_name ?? component.sn;
}

function toolName(tool: Tool): string {
  return `${tool.label ?? tool.code} · ${tool.code}`;
}

function glueName(batch: GlueBatch): string {
  return `${batch.batch_no} · ${batch.glue_type}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Validate `Institute.settings.assembly_tool_slots` (docs/05 §8, docs/07).
 * Anything missing or malformed returns `null`, which keeps the wizard on
 * the legacy single-tool layout instead of guessing at a broken config. */
function parseAssemblyToolSlots(settings: unknown): AssemblyToolSlot[] | null {
  if (!isRecord(settings)) return null;
  const raw = settings.assembly_tool_slots;
  if (!Array.isArray(raw)) return null;
  const seen = new Set<string>();
  const slots: AssemblyToolSlot[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    const key = entry.key;
    const label = entry.label;
    if (typeof key !== "string" || key.trim() === "" || seen.has(key)) continue;
    if (typeof label !== "string" || label.trim() === "") continue;
    const kinds = Array.isArray(entry.kinds)
      ? entry.kinds.filter((item): item is string => typeof item === "string")
      : undefined;
    const propertyKey = typeof entry.property_key === "string" ? entry.property_key : undefined;
    seen.add(key);
    slots.push({
      key,
      label,
      kinds: kinds !== undefined && kinds.length > 0 ? kinds : undefined,
      multiple: entry.multiple === true,
      property_key: propertyKey,
    });
  }
  return slots.length > 0 ? slots : null;
}

function slotIsMultiple(slotDef: AssemblyToolSlot): boolean {
  return slotDef.multiple === true;
}

/** `multiple` slots accept up to four tools (e.g. two glue jigs plus two
 * pickup tools); every other slot takes exactly one. */
function slotCapacity(slotDef: AssemblyToolSlot): number {
  return slotIsMultiple(slotDef) ? 4 : 1;
}

function slotAcceptsKind(slotDef: AssemblyToolSlot, tool: Tool): boolean {
  return slotDef.kinds === undefined || slotDef.kinds.length === 0 || slotDef.kinds.includes(tool.kind);
}

function hasRoomFor(slotDef: AssemblyToolSlot, selected: Tool[], tool: Tool): boolean {
  return selected.some((item) => item.id === tool.id) || selected.length < slotCapacity(slotDef);
}

/** Route a scanned tool to the slot it obviously belongs to: when exactly
 * one non-full slot accepts the tool's kind, target it regardless of which
 * slot is currently active — that is the whole point of a keyword-wedge
 * scanner loop. Zero or multiple matches fall back to the active slot so the
 * existing kind/capacity checks can explain the rejection. */
function resolveScanTargetSlot(
  slots: AssemblyToolSlot[],
  selections: Record<string, Tool[]>,
  tool: Tool,
  activeKey: string | null,
): AssemblyToolSlot {
  const eligible = slots.filter(
    (slotDef) => slotAcceptsKind(slotDef, tool) && hasRoomFor(slotDef, selections[slotDef.key] ?? [], tool),
  );
  if (eligible.length === 1) return eligible[0];
  return slots.find((item) => item.key === activeKey) ?? slots[0];
}

/** After a slot reaches its capacity, hand the active slot to the next one
 * (wrapping) that still has room — keeps a sequential scan loop (bottom jig,
 * top jig, module jig, …) moving without an extra click per tool. */
function nextSlotWithRoom(
  slots: AssemblyToolSlot[],
  selections: Record<string, Tool[]>,
  fromKey: string,
  filledLength: number,
): string {
  const startIndex = slots.findIndex((item) => item.key === fromKey);
  for (let offset = 1; offset <= slots.length; offset += 1) {
    const candidate = slots[(startIndex + offset) % slots.length];
    const length =
      candidate.key === fromKey ? filledLength : (selections[candidate.key] ?? []).length;
    if (length < slotCapacity(candidate)) return candidate.key;
  }
  return fromKey;
}

/**
 * Scanner-first assembly flow.  Every selection is resolved from local read
 * models, then sent through the canonical server dry-run before an outbox
 * action can be staged.  This screen never performs a PDB write.
 */
export default function AssemblyWizardScreen({
  onBack,
  onStaged,
}: {
  onBack: () => void;
  onStaged: (action: OutboxAction) => void;
}) {
  const { canWrite, demo, showToast } = useAuth();
  const [parentText, setParentText] = useState("");
  const [childText, setChildText] = useState("");
  const [parent, setParent] = useState<ComponentOut | null>(null);
  const [child, setChild] = useState<ComponentOut | null>(null);
  const [scanBusy, setScanBusy] = useState<ScanRole | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  // Tool-scan rejections/errors render inline under the tool-scan form, not
  // in the bottom banner (which stays for the component/glue scan and
  // preview/stage errors).
  const [toolScanError, setToolScanError] = useState<string | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [glueBatches, setGlueBatches] = useState<GlueBatch[]>([]);
  const [resourcesLoading, setResourcesLoading] = useState(false);
  const [resourcesError, setResourcesError] = useState<string | null>(null);
  const [toolId, setToolId] = useState("");
  const [toolScan, setToolScan] = useState("");
  // Institute-configured resource slots (docs/05 §8). `null` means no
  // profile layout is configured and the legacy single-tool UI applies.
  const [toolSlots, setToolSlots] = useState<AssemblyToolSlot[] | null>(null);
  const [slotTools, setSlotTools] = useState<Record<string, Tool[]>>({});
  const [activeSlotKey, setActiveSlotKey] = useState<string | null>(null);
  const [glueBatchId, setGlueBatchId] = useState("");
  const [glueScan, setGlueScan] = useState("");
  const [slot, setSlot] = useState("");
  const [preview, setPreview] = useState<AssemblyPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [staging, setStaging] = useState(false);
  const componentScanRequest = useRef<Record<ScanRole, number>>({ parent: 0, child: 0 });
  const resourceScanRequest = useRef<Record<ResourceScanRole, number>>({ tool: 0, glue: 0 });
  const resourceScanController = useRef<Record<ResourceScanRole, AbortController | null>>({
    tool: null,
    glue: null,
  });
  const previewRequest = useRef(0);

  useEffect(
    () => () => {
      componentScanRequest.current.parent += 1;
      componentScanRequest.current.child += 1;
      resourceScanRequest.current.tool += 1;
      resourceScanRequest.current.glue += 1;
      resourceScanController.current.tool?.abort();
      resourceScanController.current.glue?.abort();
      previewRequest.current += 1;
    },
    [],
  );

  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    setToolId("");
    setGlueBatchId("");
    setToolSlots(null);
    setSlotTools({});
    setActiveSlotKey(null);
    if (parent === null) {
      setTools([]);
      setGlueBatches([]);
      return;
    }
    if (demo) {
      setTools(
        makeDemoTools().filter(
          (tool) =>
            tool.status === "active" && tool.compatible_types.includes(parent.type_code),
        ),
      );
      setGlueBatches(makeDemoGlueBatches().filter((batch) => batch.status === "in_use"));
      return;
    }

    const controller = new AbortController();
    setResourcesLoading(true);
    setResourcesError(null);
    Promise.all([
      getTools(
        {
          fits: parent.type_code,
          status: "active",
          institute: parent.institute_code,
        },
        controller.signal,
      ),
      getGlueBatches(
        { status: "in_use", institute: parent.institute_code },
        controller.signal,
      ),
    ])
      .then(([loadedTools, loadedGlue]) => {
        setTools(loadedTools);
        setGlueBatches(loadedGlue);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setResourcesError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setResourcesLoading(false);
      });
    // Independent request: an unreachable/invalid institute profile must not
    // take down tool/glue loading. Any failure here is a silent fallback to
    // the legacy single-tool layout, never a Resources-step error banner.
    getInstitutes(controller.signal)
      .then((institutes) => {
        if (controller.signal.aborted) return;
        const institute = institutes.find((item) => item.code === parent.institute_code) ?? null;
        const slots = institute === null ? null : parseAssemblyToolSlots(institute.settings);
        setToolSlots(slots);
        setActiveSlotKey(slots === null ? null : slots[0].key);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setToolSlots(null);
        setActiveSlotKey(null);
      });
    return () => controller.abort();
  }, [demo, parent]);

  function clearPreview() {
    previewRequest.current += 1;
    setPreview(null);
    setPreviewError(null);
    setPreviewing(false);
    // Every input change that invalidates the preview also dismisses a
    // stale tool-scan rejection — the operator is clearly moving on.
    setToolScanError(null);
  }

  function invalidateResourceScan(role: ResourceScanRole) {
    resourceScanRequest.current[role] += 1;
    resourceScanController.current[role]?.abort();
    resourceScanController.current[role] = null;
  }

  function invalidateParentDependents() {
    componentScanRequest.current.child += 1;
    invalidateResourceScan("tool");
    invalidateResourceScan("glue");
  }

  function clearParentDependents() {
    setChild(null);
    setChildText("");
    setToolScan("");
    setToolScanError(null);
    setGlueScan("");
    setToolId("");
    setGlueBatchId("");
    setToolSlots(null);
    setSlotTools({});
    setActiveSlotKey(null);
  }

  /** Add a scanned/quick-selected tool to one resource slot: replaces the
   * single tool for a non-`multiple` slot, appends (up to four) otherwise.
   * Silently no-ops on an already-full slot; callers that need to surface
   * that as an error check capacity first. Once the slot reaches capacity,
   * hands the active slot to the next one with room (wrapping). */
  function addToolToSlot(slotDef: AssemblyToolSlot, tool: Tool) {
    const existing = slotTools[slotDef.key] ?? [];
    if (existing.some((item) => item.id === tool.id)) {
      setActiveSlotKey(slotDef.key);
      return;
    }
    const capacity = slotCapacity(slotDef);
    if (slotIsMultiple(slotDef) && existing.length >= capacity) return;
    const next = slotIsMultiple(slotDef) ? [...existing, tool] : [tool];
    setSlotTools((current) => ({ ...current, [slotDef.key]: next }));
    setTools((current) =>
      current.some((item) => item.id === tool.id) ? current : [...current, tool],
    );
    if (toolSlots !== null && next.length >= capacity) {
      setActiveSlotKey(nextSlotWithRoom(toolSlots, slotTools, slotDef.key, next.length));
    } else {
      setActiveSlotKey(slotDef.key);
    }
  }

  function removeToolFromSlot(slotKey: string, toolId: number) {
    setSlotTools((current) => ({
      ...current,
      [slotKey]: (current[slotKey] ?? []).filter((tool) => tool.id !== toolId),
    }));
    clearPreview();
  }

  async function resolveComponent(role: ScanRole) {
    const raw = (role === "parent" ? parentText : childText).trim();
    if (raw === "") return;
    const requestId = ++componentScanRequest.current[role];
    if (role === "parent") {
      invalidateParentDependents();
      clearParentDependents();
      setParent(null);
    } else {
      setChild(null);
    }
    clearPreview();
    setScanBusy(role);
    setScanError(null);
    try {
      let component: ComponentOut | null;
      if (demo) {
        component = scanDemoComponent(raw);
        if (component === null) throw new Error(t.assembly.scanNotFound(raw));
      } else {
        component = await scanAssemblyComponent(raw);
      }
      if (requestId !== componentScanRequest.current[role]) return;
      if (role === "parent") {
        setParent(component);
        setParentText(component.sn);
      } else {
        setChild(component);
        setChildText(component.sn);
      }
    } catch (error: unknown) {
      if (requestId !== componentScanRequest.current[role]) return;
      setScanError(
        error instanceof ApiError && error.status === 404
          ? t.assembly.scanNotFound(raw)
          : errorMessage(error),
      );
    } finally {
      if (requestId === componentScanRequest.current[role]) setScanBusy(null);
    }
  }

  async function handleComponentScan(event: FormEvent, role: ScanRole) {
    event.preventDefault();
    await resolveComponent(role);
  }

  async function handleToolScan(event: FormEvent) {
    event.preventDefault();
    const value = toolScan.trim();
    if (value === "" || parent === null) return;
    invalidateResourceScan("tool");
    const requestId = resourceScanRequest.current.tool;
    const controller = new AbortController();
    resourceScanController.current.tool = controller;
    setToolScanError(null);
    try {
      const tool = demo
        ? scanDemoTool(value)
        : await scanTool(value, parent.institute_code, controller.signal);
      if (requestId !== resourceScanRequest.current.tool) return;
      if (tool === null) throw new Error(t.tools.scanNotFound(value));
      if (tool.status !== "active" || !tool.compatible_types.includes(parent.type_code)) {
        setToolScanError(t.assembly.toolScanRejected(tool.code, parent.type_code));
        setToolScan("");
        return;
      }
      if (toolSlots !== null) {
        // Kind-based routing: an unambiguous match wins over whatever slot
        // happens to be active, so a fast scan loop never needs a click.
        const targetSlot = resolveScanTargetSlot(toolSlots, slotTools, tool, activeSlotKey);
        if (!slotAcceptsKind(targetSlot, tool)) {
          setToolScanError(t.assembly.toolScanRejectedForSlot(tool.code, targetSlot.label));
          setToolScan("");
          return;
        }
        const currentSelection = slotTools[targetSlot.key] ?? [];
        const alreadySelected = currentSelection.some((item) => item.id === tool.id);
        const capacity = slotCapacity(targetSlot);
        if (!alreadySelected && currentSelection.length >= capacity) {
          setToolScanError(t.assembly.toolSlotFull(targetSlot.label, capacity));
          setToolScan("");
          return;
        }
        addToolToSlot(targetSlot, tool);
      } else {
        setTools((current) =>
          current.some((item) => item.id === tool.id) ? current : [...current, tool],
        );
        setToolId(String(tool.id));
      }
      setToolScan("");
      clearPreview();
    } catch (error: unknown) {
      if (requestId !== resourceScanRequest.current.tool || controller.signal.aborted) return;
      setToolScanError(errorMessage(error));
    } finally {
      if (requestId === resourceScanRequest.current.tool) {
        resourceScanController.current.tool = null;
      }
    }
  }

  async function handleGlueScan(event: FormEvent) {
    event.preventDefault();
    const value = glueScan.trim();
    if (value === "" || parent === null) return;
    invalidateResourceScan("glue");
    const requestId = resourceScanRequest.current.glue;
    const controller = new AbortController();
    resourceScanController.current.glue = controller;
    setScanError(null);
    try {
      const batch = demo
        ? (makeDemoGlueBatches().find(
            (item) =>
              item.batch_no.toUpperCase() === value.toUpperCase() ||
              (item.pdb_sn ?? "").toUpperCase() === value.toUpperCase(),
          ) ?? null)
        : await scanGlueBatch(value, parent.institute_code, controller.signal);
      if (requestId !== resourceScanRequest.current.glue) return;
      if (batch === null) throw new Error(t.assembly.glueScanNotFound(value));
      if (batch.status !== "in_use" || batch.pot_life_expired) {
        setScanError(t.assembly.glueScanRejected(batch.batch_no));
        return;
      }
      setGlueBatches((current) =>
        current.some((item) => item.id === batch.id) ? current : [...current, batch],
      );
      setGlueBatchId(String(batch.id));
      setGlueScan("");
      clearPreview();
    } catch (error: unknown) {
      if (requestId !== resourceScanRequest.current.glue || controller.signal.aborted) return;
      setScanError(errorMessage(error));
    } finally {
      if (requestId === resourceScanRequest.current.glue) {
        resourceScanController.current.glue = null;
      }
    }
  }

  function draft(): AssemblyDraft | null {
    if (parent === null || child === null || slot.trim() === "") return null;
    if (toolSlots === null) {
      if (toolId === "") return null;
      return {
        parent_sn: parent.sn,
        child_sn: child.sn,
        slot: slot.trim(),
        tool_id: Number(toolId),
        glue_batch_id: glueBatchId === "" ? null : Number(glueBatchId),
      };
    }
    const toolsBySlot: Record<string, number[]> = {};
    for (const slotDef of toolSlots) {
      const selected = slotTools[slotDef.key] ?? [];
      if (selected.length < 1 || selected.length > slotCapacity(slotDef)) return null;
      toolsBySlot[slotDef.key] = selected.map((tool) => tool.id);
    }
    return {
      parent_sn: parent.sn,
      child_sn: child.sn,
      slot: slot.trim(),
      tools: toolsBySlot,
      glue_batch_id: glueBatchId === "" ? null : Number(glueBatchId),
    };
  }

  async function runPreview() {
    const value = draft();
    if (value === null) {
      setPreviewError(t.assembly.incomplete);
      return;
    }
    setPreviewing(true);
    setPreviewError(null);
    const requestId = ++previewRequest.current;
    try {
      const next = demo
        ? makeDemoAssemblyPreview(
            parent as ComponentOut,
            child as ComponentOut,
            tools.find((tool) => tool.id === Number(toolId)) as Tool,
            glueBatches.find((batch) => batch.id === Number(glueBatchId)) ?? null,
            value.slot,
          )
        : await postAssemblyPreview(value);
      if (requestId === previewRequest.current) setPreview(next);
    } catch (error: unknown) {
      if (requestId === previewRequest.current) setPreviewError(errorMessage(error));
    } finally {
      if (requestId === previewRequest.current) setPreviewing(false);
    }
  }

  async function stageAssembly() {
    const value = draft();
    if (value === null || preview === null || !preview.valid) return;
    setStaging(true);
    setPreviewError(null);
    try {
      const action = demo
        ? stageDemoAssemblyAction(value, preview)
        : (await postAssemblyAction(value)).action;
      showToast(t.assembly.staged(action.id));
      onStaged(action);
    } catch (error: unknown) {
      setPreviewError(t.assembly.stageFailed(errorMessage(error)));
    } finally {
      setStaging(false);
    }
  }

  const selectedGlue = glueBatches.find((batch) => batch.id === Number(glueBatchId));

  return (
    <div className="screen assembly-wizard">
      <div className="sc-head">
        <h1>{t.assembly.title}</h1>
        <span className="sub">{t.assembly.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
        <button type="button" className="btn cta" onClick={onBack}>
          {t.assembly.back}
        </button>
      </div>

      <div className="wizard-steps" aria-label={t.assembly.progressLabel}>
        <span className={parent === null ? "active" : "done"}>1 · {t.assembly.stepParent}</span>
        <span className={parent !== null && child === null ? "active" : child ? "done" : ""}>
          2 · {t.assembly.stepChild}
        </span>
        <span className={child !== null && preview === null ? "active" : preview ? "done" : ""}>
          3 · {t.assembly.stepResources}
        </span>
        <span className={preview !== null ? "active" : ""}>4 · {t.assembly.stepReview}</span>
      </div>

      <div className="assembly-grid">
        <section className="panel assembly-scan-panel">
          <h2>{t.assembly.componentsTitle}</h2>
          <form onSubmit={(event) => void handleComponentScan(event, "parent")}>
            <label className="control-label" htmlFor="assembly-parent-scan">
              {t.assembly.parentLabel}
            </label>
            <div className="inline-form">
              <input
                id="assembly-parent-scan"
                className="search-input mono"
                value={parentText}
                onChange={(event) => {
                  componentScanRequest.current.parent += 1;
                  invalidateParentDependents();
                  setScanBusy(null);
                  setParentText(event.target.value);
                  setParent(null);
                  clearParentDependents();
                  clearPreview();
                }}
                placeholder={t.assembly.parentPlaceholder}
                autoFocus
              />
              <button className="btn primary" disabled={scanBusy !== null}>
                {scanBusy === "parent" ? t.common.loading : t.assembly.resolve}
              </button>
            </div>
          </form>
          {parent !== null && <ComponentCard component={parent} role={t.assembly.parentLabel} />}

          <form onSubmit={(event) => void handleComponentScan(event, "child")}>
            <label className="control-label" htmlFor="assembly-child-scan">
              {t.assembly.childLabel}
            </label>
            <div className="inline-form">
              <input
                id="assembly-child-scan"
                className="search-input mono"
                value={childText}
                onChange={(event) => {
                  componentScanRequest.current.child += 1;
                  setScanBusy(null);
                  setChildText(event.target.value);
                  setChild(null);
                  clearPreview();
                }}
                placeholder={t.assembly.childPlaceholder}
                disabled={parent === null}
              />
              <button className="btn primary" disabled={parent === null || scanBusy !== null}>
                {scanBusy === "child" ? t.common.loading : t.assembly.resolve}
              </button>
            </div>
          </form>
          {child !== null && <ComponentCard component={child} role={t.assembly.childLabel} />}
        </section>

        <section className="panel assembly-resources-panel">
          <h2>{t.assembly.resourcesTitle}</h2>
          {resourcesLoading && <p className="state-note">{t.common.loading}</p>}
          {resourcesError !== null && <div className="error-banner">{resourcesError}</div>}

          <label className="control-label" htmlFor="assembly-slot">
            {t.assembly.slotLabel}
          </label>
          <input
            id="assembly-slot"
            className="search-input mono"
            value={slot}
            onChange={(event) => {
              setSlot(event.target.value);
              clearPreview();
            }}
            placeholder={t.assembly.slotPlaceholder}
            disabled={child === null}
          />

          {toolSlots === null ? (
            <>
              <label className="control-label" htmlFor="assembly-tool">
                {t.assembly.toolLabel}
              </label>
              <select
                id="assembly-tool"
                className="select-input"
                value={toolId}
                onChange={(event) => {
                  invalidateResourceScan("tool");
                  setToolId(event.target.value);
                  clearPreview();
                }}
                disabled={parent === null}
              >
                <option value="">{t.assembly.chooseTool}</option>
                {tools.map((tool) => (
                  <option key={tool.id} value={tool.id}>
                    {toolName(tool)}
                  </option>
                ))}
              </select>
            </>
          ) : (
            <div className="assembly-tool-slots">
              {toolSlots.map((slotDef) => (
                <ToolSlotCard
                  key={slotDef.key}
                  slotDef={slotDef}
                  tools={tools}
                  selected={slotTools[slotDef.key] ?? []}
                  active={activeSlotKey === slotDef.key}
                  onActivate={() => setActiveSlotKey(slotDef.key)}
                  onAdd={(tool) => {
                    addToolToSlot(slotDef, tool);
                    clearPreview();
                  }}
                  onRemove={(toolId) => removeToolFromSlot(slotDef.key, toolId)}
                />
              ))}
            </div>
          )}
          {parent !== null && tools.length === 0 && !resourcesLoading && (
            <p className="hint serious-text">{t.assembly.noCompatibleTools(parent.type_code)}</p>
          )}
          <form className="inline-form" onSubmit={(event) => void handleToolScan(event)}>
            <input
              className="search-input mono"
              value={toolScan}
              onChange={(event) => {
                invalidateResourceScan("tool");
                setToolScan(event.target.value);
              }}
              placeholder={t.assembly.toolScanPlaceholder}
              disabled={parent === null}
              aria-label={t.assembly.toolScanLabel}
            />
            <button className="btn" disabled={parent === null}>
              {t.assembly.scan}
            </button>
          </form>
          {toolScanError !== null && (
            <div className="error-banner" role="alert">
              {toolScanError}
            </div>
          )}

          <label className="control-label" htmlFor="assembly-glue">
            {t.assembly.glueLabel}
          </label>
          <select
            id="assembly-glue"
            className="select-input"
            value={glueBatchId}
            onChange={(event) => {
              invalidateResourceScan("glue");
              setGlueBatchId(event.target.value);
              clearPreview();
            }}
            disabled={parent === null}
          >
            <option value="">{t.assembly.noGlue}</option>
            {glueBatches.map((batch) => (
              <option key={batch.id} value={batch.id}>
                {glueName(batch)}
              </option>
            ))}
          </select>
          {selectedGlue !== undefined && (
            <p className="hint">
              {selectedGlue.pot_life_remaining_seconds === null
                ? t.assembly.glueUntimed
                : t.assembly.glueRemaining(
                    formatDuration(selectedGlue.pot_life_remaining_seconds),
                  )}
            </p>
          )}
          <form className="inline-form" onSubmit={(event) => void handleGlueScan(event)}>
            <input
              className="search-input mono"
              value={glueScan}
              onChange={(event) => {
                invalidateResourceScan("glue");
                setGlueScan(event.target.value);
              }}
              placeholder={t.assembly.glueScanPlaceholder}
              disabled={parent === null}
              aria-label={t.assembly.glueScanLabel}
            />
            <button className="btn" disabled={parent === null}>
              {t.assembly.scan}
            </button>
          </form>

          <button
            type="button"
            className="btn primary assembly-preview-button"
            disabled={previewing || draft() === null}
            onClick={() => void runPreview()}
          >
            {previewing ? t.assembly.previewing : t.assembly.previewButton}
          </button>
        </section>
      </div>

      {scanError !== null && <div className="error-banner" role="alert">{scanError}</div>}
      {previewError !== null && <div className="error-banner" role="alert">{previewError}</div>}
      {preview !== null && (
        <AssemblyPreviewPanel
          preview={preview}
          canWrite={canWrite}
          staging={staging}
          onStage={() => void stageAssembly()}
          toolSlots={toolSlots}
        />
      )}
    </div>
  );
}

function ComponentCard({ component, role }: { component: ComponentOut; role: string }) {
  return (
    <article className="assembly-component-card">
      <div>
        <span className="field-label">{role}</span>
        <strong>{componentName(component)}</strong>
        <span className="mono muted">{component.sn}</span>
      </div>
      <div className="row-actions">
        <span className="chip neutral" title={describeComponent(component)}>
          {component.type_code}
        </span>
        <span className="chip neutral" title={component.stage}>
          {stageLabel(component.stage)}
        </span>
        <span className={component.is_dummy ? "chip green" : "chip amber"}>
          {component.is_dummy ? t.assembly.dummy : t.assembly.productionMirror}
        </span>
      </div>
    </article>
  );
}

/** One row of the profile-configured resource picker: a quick-select
 * filtered by `kinds` (when set) plus removable chips for the current
 * selection. Scanning is handled by the shared scan form above; this card
 * only needs to expose itself as the scan target on focus/click. */
function ToolSlotCard({
  slotDef,
  tools,
  selected,
  active,
  onActivate,
  onAdd,
  onRemove,
}: {
  slotDef: AssemblyToolSlot;
  tools: Tool[];
  selected: Tool[];
  active: boolean;
  onActivate: () => void;
  onAdd: (tool: Tool) => void;
  onRemove: (toolId: number) => void;
}) {
  const capacity = slotCapacity(slotDef);
  const selectedIds = new Set(selected.map((tool) => tool.id));
  const candidates = tools.filter(
    (tool) => slotAcceptsKind(slotDef, tool) && !selectedIds.has(tool.id),
  );
  const full = selected.length >= capacity;
  return (
    <div className={`assembly-tool-slot${active ? " active" : ""}`}>
      <div className="assembly-tool-slot-head">
        <button
          type="button"
          className="link-btn assembly-tool-slot-label"
          aria-pressed={active}
          onClick={onActivate}
        >
          {slotDef.label}
        </button>
        {active && (
          // Active-slot indicator is never colour-only: a labelled chip
          // (not just the card's accent border) plus `role="status"` so a
          // screen reader also hears where auto-advance just routed to.
          <span className="chip assembly-tool-slot-target" role="status">
            {t.assembly.toolSlotScanTarget(slotDef.label)}
          </span>
        )}
        <span className="mono muted assembly-tool-slot-count">
          {selected.length}/{capacity}
        </span>
      </div>
      <div className="chip-row assembly-tool-slot-chips">
        {selected.map((tool) => (
          <span className="chip neutral removable-chip" key={tool.id}>
            {toolName(tool)}
            <button
              type="button"
              className="chip-remove"
              aria-label={t.assembly.toolSlotRemove(tool.code, slotDef.label)}
              onClick={() => onRemove(tool.id)}
            >
              ×
            </button>
          </span>
        ))}
        {selected.length === 0 && (
          <span className="assembly-tool-slot-hint serious-text">
            {t.assembly.toolSlotRequired(slotDef.label)}
          </span>
        )}
      </div>
      <select
        className="select-input"
        aria-label={t.assembly.toolSlotQuickSelectLabel(slotDef.label)}
        value=""
        onFocus={onActivate}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "") return;
          const tool = candidates.find((item) => String(item.id) === value);
          if (tool !== undefined) onAdd(tool);
        }}
        disabled={full || candidates.length === 0}
      >
        <option value="">{t.assembly.toolSlotChoosePlaceholder}</option>
        {candidates.map((tool) => (
          <option key={tool.id} value={tool.id}>
            {toolName(tool)}
          </option>
        ))}
      </select>
      {full && (
        <p className="assembly-tool-slot-hint">{t.assembly.toolSlotFull(slotDef.label, capacity)}</p>
      )}
      {/* The broader "no tool at all for this module type" hint above
       * already covers an empty `tools` list; repeating it per slot would
       * just be noise. */}
      {!full && candidates.length === 0 && tools.length > 0 && (
        <p className="assembly-tool-slot-hint serious-text">
          {t.assembly.toolSlotNoCandidates(slotDef.label)}
        </p>
      )}
    </div>
  );
}

function AssemblyPreviewPanel({
  preview,
  canWrite,
  staging,
  onStage,
  toolSlots,
}: {
  preview: AssemblyPreview;
  canWrite: boolean;
  staging: boolean;
  onStage: () => void;
  toolSlots: AssemblyToolSlot[] | null;
}) {
  return (
    <section className="panel assembly-preview" aria-live="polite">
      <div className="assembly-preview-head">
        <div>
          <h2>{t.assembly.previewTitle}</h2>
          <strong>{preview.summary}</strong>
        </div>
        <span className={preview.valid ? "chip green" : "chip red"}>
          {preview.valid ? t.assembly.previewReady : t.assembly.previewBlocked}
        </span>
      </div>
      {preview.issues.length > 0 && (
        <div className="assembly-findings serious" role="alert">
          <strong>{t.assembly.issuesTitle}</strong>
          <ul>{preview.issues.map((issue) => <li key={issue.code}>{issue.message}</li>)}</ul>
        </div>
      )}
      {preview.warnings.length > 0 && (
        <div className="assembly-findings warning">
          <strong>{t.assembly.warningsTitle}</strong>
          <ul>{preview.warnings.map((warning) => <li key={warning.code}>{warning.message}</li>)}</ul>
        </div>
      )}
      <dl className="kv assembly-preview-kv">
        {toolSlots === null ? (
          <>
            <dt>{t.assembly.previewTool}</dt>
            <dd>{preview.tool?.code ?? t.common.none}</dd>
          </>
        ) : (
          // Server-confirmed selection (`AssemblyPreviewOut.tools`), not the
          // locally selected tools — the dry-run is the source of truth.
          toolSlots.map((slotDef) => (
            <span className="assembly-property" key={slotDef.key}>
              <dt>{slotDef.label}</dt>
              <dd>
                {(preview.tools?.[slotDef.key] ?? []).map((tool) => tool.code).join(", ") ||
                  t.common.none}
              </dd>
            </span>
          ))
        )}
        <dt>{t.assembly.previewGlue}</dt>
        <dd>{preview.glue_batch?.batch_no ?? t.common.none}</dd>
        <dt>{t.assembly.previewSlot}</dt>
        <dd>{preview.slot}</dd>
      </dl>
      {Object.keys(preview.pdb_properties).length > 0 && (
        <details className="history assembly-properties">
          <summary>{t.assembly.pdbProperties}</summary>
          <dl className="kv">
            {Object.entries(preview.pdb_properties).map(([key, value]) => (
              <span className="assembly-property" key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </span>
            ))}
          </dl>
        </details>
      )}
      {!preview.submittable && preview.valid && (
        <div className="info-banner" role="status">
          {t.assembly.notSubmittable}
        </div>
      )}
      <div className="action-controls assembly-preview-actions">
        <span className="hint">{t.assembly.stageHint}</span>
        <button
          type="button"
          className="btn primary"
          disabled={!canWrite || !preview.valid || staging}
          onClick={onStage}
        >
          {staging ? t.assembly.staging : t.assembly.stageButton}
        </button>
      </div>
    </section>
  );
}
