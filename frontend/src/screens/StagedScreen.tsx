/**
 * Staged work queue (spec §D) — the approval half of the worksheet flow: a
 * value is entered in the module's own table, staged as a ghost, and judged
 * here.
 *
 * For that judgement to be informed, a staged test upload has to show what it
 * actually proposes. The outbox action's own payload deliberately carries only
 * routing metadata (ingest id, SN, test type, run number) — the measured values
 * live in the ingest file. The honest client-side source for them is the
 * component preview: `projected.ghost_tests[]` contains one `ghost: true` entry per
 * open `upload_test_run`, keyed back by `outbox_action_id`, built server-side
 * from that same ingest payload (`preview._ghost_test`). No new endpoint, no
 * client-side re-derivation of what will be submitted.
 *
 * The ghost carries its results verbatim, so this screen applies the worksheet's
 * compaction contract (spec §H1) itself: a few scalars inline, arrays and
 * dict-valued results as a count chip only. A raw curve or per-position map must
 * never reach the DOM here either — that is the wall of numbers the worksheet
 * exists to remove, and it would bury exactly the values an approver reads.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SyntheticEvent } from "react";
import {
  ApiError,
  componentAttachmentUrl,
  getComponentPreview,
  getComponentThumbnails,
  getComponents,
  getOutbox,
  getOutboxAudit,
} from "../api";
import type {
  AuditEvent,
  ComponentOut,
  ComponentPreviewAction,
  ComponentPreviewTest,
  ComponentThumbnail,
  OutboxAction,
  OutboxStatus,
  WorksheetArraySummary,
  WorksheetScalar,
} from "../api";
import { useAuth } from "../auth";
import { filterDemoComponents, makeDemoOutbox } from "../demoData";
import {
  DerivedDetail,
  DerivedVerdicts,
  parseWorksheetDerived,
} from "../GlueDerivation";
import { formatTimestamp, t } from "../i18n";
import {
  canDiscard,
  canPush,
  discardStagedAction,
  pushToPdb,
} from "../stagedActions";
import { formatScalar } from "../TestResults";
import { describeComponent, stageChipClass, stageLabel } from "../ui";

type BusyAction = { id: number; kind: "push" | "discard" };

type ActionGroup = {
  key: string;
  sn: string | null;
  localName: string;
  component: ComponentOut | null;
  actions: OutboxAction[];
};

type SubmissionScope = {
  submittable: boolean;
  reason: string | null;
};

const TERMINAL = new Set<OutboxStatus>(["confirmed", "cancelled"]);

const STATUS_CHIP: Record<OutboxStatus, string> = {
  draft: "chip neutral",
  validated: "chip neutral",
  approved: "chip amber",
  submitted: "chip amber",
  confirmed: "chip green",
  failed: "chip red",
  cancelled: "chip muted",
};

const TEST_UPLOAD_KINDS = new Set(["upload_test_run", "uploadTestRun"]);

/** How many scalars are shown inline before the rest collapses into `+n`. */
const INLINE_SCALARS = 3;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isTestUpload(action: OutboxAction): boolean {
  return TEST_UPLOAD_KINDS.has(action.kind);
}

type CompactValues = {
  /** Filled scalars first; empty ones keep their relative order at the end. */
  scalars: WorksheetScalar[];
  /** Arrays and maps, reduced to their extent. Never the data itself. */
  arrays: WorksheetArraySummary[];
};

/**
 * Client-side application of the worksheet's payload contract (spec §H1) to a
 * ghost test. Same three rules as the server-side projection: a dict counts
 * like an array (key count, rendered as "entries"), filled scalars sort first
 * so a run whose first fields are empty still shows real numbers, and neither
 * the list nor the dict is ever reproduced.
 */
export function compactStagedValues(test: ComponentPreviewTest): CompactValues {
  const filled: WorksheetScalar[] = [];
  const empty: WorksheetScalar[] = [];
  const arrays: WorksheetArraySummary[] = [];

  for (const [code, value] of Object.entries(test.results ?? {})) {
    const meta = test.result_meta?.[code];
    const metaName = typeof meta?.name === "string" ? meta.name : "";
    const name = metaName === "" ? code : metaName;
    if (Array.isArray(value)) {
      arrays.push({ code, name, points: value.length, kind: "array" });
      continue;
    }
    if (typeof value === "object" && value !== null) {
      arrays.push({ code, name, points: Object.keys(value).length, kind: "map" });
      continue;
    }
    const scalar: WorksheetScalar = { code, name, value };
    if (value === null || value === undefined || value === "") empty.push(scalar);
    else filled.push(scalar);
  }

  return { scalars: [...filled, ...empty], arrays };
}

/** Shared with the worksheet on purpose: "⌁ 59 pts" / "⌁ 20 entries". */
function arraySummaryLabel(array: WorksheetArraySummary): string {
  return array.kind === "map"
    ? t.worksheet.mapEntries(array.points)
    : t.worksheet.arrayPoints(array.points);
}

function scalarTitle(scalars: WorksheetScalar[]): string {
  return scalars.map((scalar) => `${scalar.name} ${formatScalar(scalar.value)}`).join(", ");
}

function runNumberText(value: string | number | null): string | null {
  if (value === null) return null;
  const text = String(value).trim();
  return text === "" ? null : t.testResults.runNumber(text);
}

function measuredAtText(value: string | null): string | null {
  if (value === null) return null;
  const parsed = new Date(value);
  return t.staged.valuesMeasured(
    Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(),
  );
}

function payloadString(action: OutboxAction, key: string): string | null {
  const value = action.payload[key];
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function actionSerial(action: OutboxAction): string | null {
  for (const key of ["component_sn", "sn", "parent_sn", "parent"]) {
    const value = payloadString(action, key);
    if (value !== null) return value;
  }
  const items = action.payload.items;
  if (Array.isArray(items)) {
    const first = items.find((item): item is string => typeof item === "string" && item !== "");
    return first ?? null;
  }
  return null;
}

function actionLocalName(action: OutboxAction): string | null {
  return payloadString(action, "local_name");
}

function summarizeAction(action: OutboxAction): string {
  if (action.kind === "stage_move" || action.kind === "setStage") {
    const target = payloadString(action, "to_stage") ?? payloadString(action, "stage");
    return target === null ? t.staged.kinds.stage_move : t.staged.stageSummary(stageLabel(target));
  }
  if (action.kind === "upload_test_run" || action.kind === "uploadTestRun") {
    const testType = payloadString(action, "test_type") ?? payloadString(action, "testType");
    return testType === null ? t.staged.kinds.upload_test_run : t.staged.uploadSummary(testType);
  }
  if (action.kind === "register_component") {
    const componentType = payloadString(action, "component_type");
    return componentType === null
      ? t.staged.kinds.register_component
      : t.staged.registerSummary(componentType);
  }
  if (action.kind === "assembleModule" || action.kind === "assemble_component") {
    const child = payloadString(action, "child_sn") ?? payloadString(action, "child");
    return child === null ? t.staged.kinds.assemble_component : t.staged.assemblySummary(child);
  }
  if (action.kind === "createShipment") {
    const recipient = payloadString(action, "recipient");
    return recipient === null ? t.staged.kinds.createShipment : t.staged.shipmentSummary(recipient);
  }
  return t.staged.kinds[action.kind] ?? action.kind;
}

function groupActions(actions: OutboxAction[], components: ComponentOut[]): ActionGroup[] {
  const componentBySn = new Map(components.map((component) => [component.sn, component]));
  const groups = new Map<string, ActionGroup>();

  for (const action of actions) {
    const sn = actionSerial(action);
    const component = sn === null ? null : (componentBySn.get(sn) ?? null);
    const pendingName = actionLocalName(action);
    const key = sn !== null ? `sn:${sn}` : `pending:${pendingName ?? action.kind}:${action.id}`;
    const existing = groups.get(key);
    if (existing !== undefined) {
      existing.actions.push(action);
      continue;
    }
    groups.set(key, {
      key,
      sn,
      component,
      localName:
        component?.local_name ?? pendingName ?? sn ?? t.staged.unassignedComponent,
      actions: [action],
    });
  }

  return [...groups.values()].sort((left, right) =>
    left.localName.localeCompare(right.localName, undefined, { numeric: true }),
  );
}

function demoAudit(actions: OutboxAction[]): AuditEvent[] {
  return actions.map((action) => ({
    id: action.id * 10,
    ts: action.updated_at,
    actor: action.created_by,
    user_id: null,
    action: "outbox.demo_snapshot",
    subject: `outbox:${action.id}`,
    detail: { kind: action.kind, status: action.status },
    outbox_action_id: action.id,
  }));
}

function formatAuditValue(value: unknown): string {
  if (value === null || value === undefined) return t.common.none;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .filter((item) => ["string", "number", "boolean"].includes(typeof item))
      .map(String)
      .join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .filter(([, item]) =>
        item === null || ["string", "number", "boolean"].includes(typeof item),
      )
      .map(([key, item]) => `${key}: ${String(item)}`)
      .join(" · ");
  }
  return t.staged.auditValueUnavailable;
}

export default function StagedScreen({
  onOpenComponent,
}: {
  onOpenComponent: (sn: string) => void;
}) {
  const { canWrite, user, showToast } = useAuth();
  const [actions, setActions] = useState<OutboxAction[]>([]);
  const [components, setComponents] = useState<ComponentOut[]>([]);
  const [thumbnails, setThumbnails] = useState<Record<string, ComponentThumbnail>>({});
  const [previewActions, setPreviewActions] = useState<Record<number, ComponentPreviewAction>>({});
  // Ghost tests keyed by the outbox action they belong to: the measured values
  // this screen approves (see the module docstring for why this is the source).
  const [stagedTests, setStagedTests] = useState<Record<number, ComponentPreviewTest>>({});
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [busy, setBusy] = useState<BusyAction | null>(null);
  const demoStore = useRef<OutboxAction[] | null>(null);

  const load = useCallback(async (options?: { silent?: boolean }) => {
    if (options?.silent !== true) setLoading(true);
    setError(null);
    try {
      const loadedActions = await getOutbox();
      setActions(loadedActions);
      setDemo(false);

      const [componentResult, thumbnailResult] = await Promise.allSettled([
        getComponents(),
        getComponentThumbnails(),
      ]);
      const loadedComponents =
        componentResult.status === "fulfilled" ? componentResult.value : [];
      setComponents(loadedComponents);
      setThumbnails(thumbnailResult.status === "fulfilled" ? thumbnailResult.value : {});
      setAudit([]);

      const knownSerials = new Set(loadedComponents.map((component) => component.sn));
      const targetSerials = [
        ...new Set(
          loadedActions
            .map(actionSerial)
            .filter((sn): sn is string => sn !== null && knownSerials.has(sn)),
        ),
      ];
      const previewResults = await Promise.allSettled(
        targetSerials.map((sn) => getComponentPreview(sn)),
      );
      const metadata: Record<number, ComponentPreviewAction> = {};
      const ghosts: Record<number, ComponentPreviewTest> = {};
      for (const result of previewResults) {
        if (result.status !== "fulfilled") continue;
        for (const action of result.value.staged_actions) metadata[action.id] = action;
        // A preview built before the ghost projection existed may omit
        // `projected.ghost_tests`; a missing block means "values unknown",
        // which the card says out loud instead of guessing.
        const tests = result.value.projected?.ghost_tests;
        if (!Array.isArray(tests)) continue;
        for (const test of tests) {
          if (test.ghost && test.outbox_action_id !== null) ghosts[test.outbox_action_id] = test;
        }
      }
      setPreviewActions(metadata);
      setStagedTests(ghosts);
    } catch (caught) {
      if (caught instanceof ApiError && caught.isNetwork) {
        if (demoStore.current === null) demoStore.current = makeDemoOutbox();
        const demoActions = demoStore.current;
        setActions(demoActions);
        setComponents(filterDemoComponents("", "", ""));
        setThumbnails({});
        setPreviewActions({});
        setStagedTests({});
        setAudit(demoAudit(demoActions));
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

  const openActions = useMemo(
    () => actions.filter((action) => !TERMINAL.has(action.status)),
    [actions],
  );
  const historyActions = useMemo(
    () => actions.filter((action) => TERMINAL.has(action.status)),
    [actions],
  );
  const openGroups = useMemo(
    () => groupActions(openActions, components),
    [openActions, components],
  );
  const historyGroups = useMemo(
    () => groupActions(historyActions, components),
    [historyActions, components],
  );
  const failedCount = openActions.filter((action) => action.status === "failed").length;

  function componentFor(action: OutboxAction): ComponentOut | null {
    const sn = actionSerial(action);
    if (sn === null) return null;
    return components.find((component) => component.sn === sn) ?? null;
  }

  function submissionScope(action: OutboxAction): SubmissionScope {
    const preview = previewActions[action.id];
    if (preview !== undefined) {
      return { submittable: preview.submittable, reason: preview.submittable_reason };
    }
    // Registration is constrained by the backend to DUMMY modules/hybrids and
    // has no mirrored component yet, so no component preview can exist for it.
    if (action.kind === "register_component") return { submittable: true, reason: null };
    // Never infer assembly eligibility from its parent alone. A missing
    // server projection also means tool/glue/child revalidation is missing.
    if (action.kind === "assemble_component" && !demo) {
      return { submittable: false, reason: "write_scope_unavailable" };
    }
    if (action.kind === "assemble_component") {
      const parentSn = payloadString(action, "parent_sn");
      const childSn = payloadString(action, "child_sn");
      const participants = components.filter(
        (item) => item.sn === parentSn || item.sn === childSn,
      );
      const safeTypes = new Set(["MODULE", "HYBRID"]);
      const eligible =
        participants.length === 2 &&
        participants.every((item) => item.is_dummy && safeTypes.has(item.component_type));
      return {
        submittable: eligible,
        reason: eligible ? null : "write_scope_unavailable",
      };
    }
    const component = componentFor(action);
    if (component?.is_dummy === true) return { submittable: true, reason: null };
    if (component !== null) return { submittable: false, reason: "not_dummy" };
    return { submittable: false, reason: "write_scope_unavailable" };
  }

  function canWriteAction(action: OutboxAction): boolean {
    return (
      canWrite &&
      (demo || user?.institute_id === null || user?.institute_id === action.institute_id)
    );
  }

  function updateDemoAction(action: OutboxAction, status: OutboxStatus) {
    if (demoStore.current === null) return;
    demoStore.current = demoStore.current.map((current) =>
      current.id === action.id
        ? {
            ...current,
            status,
            attempts: status === "submitted" ? current.attempts + 1 : current.attempts,
            error: status === "submitted" ? null : current.error,
            updated_at: new Date().toISOString(),
          }
        : current,
    );
    setActions(demoStore.current);
    setAudit(demoAudit(demoStore.current));
  }

  async function handlePush(action: OutboxAction) {
    const scope = submissionScope(action);
    if (!canWriteAction(action) || !scope.submittable || !canPush(action.status)) return;
    setBusy({ id: action.id, kind: "push" });
    setNotice(null);
    try {
      if (demo) {
        updateDemoAction(action, "submitted");
      } else {
        await pushToPdb(action, user?.email ?? "ui-user");
        await load({ silent: true });
      }
      showToast(t.staged.pushed(summarizeAction(action)));
    } catch (caught) {
      setNotice(`${t.staged.pushFailed}: ${errorMessage(caught)}`);
      if (!(caught instanceof ApiError && caught.isNetwork)) await load({ silent: true });
    } finally {
      setBusy(null);
    }
  }

  async function handleDiscard(action: OutboxAction) {
    if (!canWriteAction(action) || !canDiscard(action.status)) return;
    setBusy({ id: action.id, kind: "discard" });
    setNotice(null);
    try {
      if (demo) {
        updateDemoAction(action, "cancelled");
      } else {
        await discardStagedAction(action, user?.email ?? "ui-user");
        await load({ silent: true });
      }
      showToast(t.staged.discarded(summarizeAction(action)));
    } catch (caught) {
      setNotice(`${t.staged.discardFailed}: ${errorMessage(caught)}`);
      if (!(caught instanceof ApiError && caught.isNetwork)) await load({ silent: true });
    } finally {
      setBusy(null);
    }
  }

  function auditFor(action: OutboxAction): AuditEvent[] {
    return audit.filter(
      (event) =>
        event.outbox_action_id === action.id || event.subject === `outbox:${action.id}`,
    );
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.staged}</h1>
        <span className="sub">{t.staged.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
        <button
          type="button"
          className="btn cta"
          disabled={loading || busy !== null}
          onClick={() => void load()}
        >
          {t.staged.refresh}
        </button>
      </div>
      {demo && (
        <div className="toolbar">
          <span className="muted">{t.common.demoNote}</span>
        </div>
      )}
      <div className="staged-overview" aria-label={t.staged.overviewLabel}>
        <div className="panel staged-overview-item">
          <span className="field-label">{t.staged.openActions}</span>
          <strong>{openActions.length}</strong>
        </div>
        <div className="panel staged-overview-item">
          <span className="field-label">{t.staged.components}</span>
          <strong>{openGroups.length}</strong>
        </div>
        <div className="panel staged-overview-item">
          <span className="field-label">{t.staged.needsAttention}</span>
          <strong className={failedCount > 0 ? "error-text" : undefined}>{failedCount}</strong>
        </div>
      </div>
      {notice !== null && (
        <div className="error-banner" role="alert">
          <span>{notice}</span>
          <button type="button" className="btn" onClick={() => setNotice(null)}>
            {t.common.dismiss}
          </button>
        </div>
      )}
      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.staged.loadError}: {error}
          </span>
          <button type="button" className="btn" onClick={() => void load()}>
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : openGroups.length === 0 ? (
        <p className="state-note">{t.staged.empty}</p>
      ) : (
        <div className="staged-groups">
          {openGroups.map((group) => (
            <ComponentActionGroup
              key={group.key}
              group={group}
              thumbnails={thumbnails}
              stagedTests={stagedTests}
              canWriteAction={canWriteAction}
              busy={busy}
              history={false}
              demo={demo}
              auditFor={auditFor}
              submissionScope={submissionScope}
              onOpenComponent={onOpenComponent}
              onPush={handlePush}
              onDiscard={handleDiscard}
            />
          ))}
        </div>
      )}
      {historyActions.length > 0 && (
        <details className="panel staged-history">
          <summary>
            <span>{t.staged.history}</span>
            <span className="chip muted">{historyActions.length}</span>
          </summary>
          <div className="staged-history-groups">
            {historyGroups.map((group) => (
              <ComponentActionGroup
                key={group.key}
                group={group}
                thumbnails={thumbnails}
                stagedTests={stagedTests}
                canWriteAction={() => false}
                busy={busy}
                history
                demo={demo}
                auditFor={auditFor}
                submissionScope={submissionScope}
                onOpenComponent={onOpenComponent}
                onPush={handlePush}
                onDiscard={handleDiscard}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function ComponentActionGroup({
  group,
  thumbnails,
  stagedTests,
  canWriteAction,
  busy,
  history,
  demo,
  auditFor,
  submissionScope,
  onOpenComponent,
  onPush,
  onDiscard,
}: {
  group: ActionGroup;
  thumbnails: Record<string, ComponentThumbnail>;
  stagedTests: Record<number, ComponentPreviewTest>;
  canWriteAction: (action: OutboxAction) => boolean;
  busy: BusyAction | null;
  history: boolean;
  demo: boolean;
  auditFor: (action: OutboxAction) => AuditEvent[];
  submissionScope: (action: OutboxAction) => SubmissionScope;
  onOpenComponent: (sn: string) => void;
  onPush: (action: OutboxAction) => Promise<void>;
  onDiscard: (action: OutboxAction) => Promise<void>;
}) {
  const thumbnail = group.sn === null ? undefined : thumbnails[group.sn];
  return (
    <section className={history ? "staged-component-group history" : "panel staged-component-group"}>
      <header className="staged-component-head">
        {thumbnail !== undefined && group.sn !== null ? (
          <img
            /* `thumbnail.sn` is the component whose mirror holds the bytes:
               a tile borrowed from an assembled part is filed under that part,
               and asking for it under this group's serial would 404. The alt
               text names the part for the same reason the list marks it. */
            className={
              thumbnail.part === null
                ? "staged-component-thumb"
                : "staged-component-thumb is-borrowed"
            }
            src={componentAttachmentUrl(thumbnail.sn, thumbnail.code, thumbnail.source)}
            alt={
              thumbnail.part === null
                ? t.staged.thumbnailAlt(group.localName)
                : t.images.borrowedFrom(
                    describeComponent({
                      component_type: thumbnail.part.component_type,
                      type_code: thumbnail.part.type_code,
                    }),
                    thumbnail.part.local_name ?? thumbnail.part.sn,
                  )
            }
          />
        ) : (
          <span className="staged-component-thumb placeholder" aria-hidden="true">
            {group.localName.slice(0, 1).toUpperCase()}
          </span>
        )}
        <div className="staged-component-identity">
          {group.sn !== null ? (
            <button
              type="button"
              className="link-btn staged-component-name"
              onClick={() => onOpenComponent(group.sn as string)}
            >
              {group.localName}
            </button>
          ) : (
            <strong className="staged-component-name">{group.localName}</strong>
          )}
          <span className="mono muted">{group.sn ?? t.staged.serialPending}</span>
        </div>
        {group.component !== null ? (
          <span className={stageChipClass(group.component.stage)} title={group.component.stage}>
            {stageLabel(group.component.stage)}
          </span>
        ) : (
          <span className="chip muted">{t.staged.stagePending}</span>
        )}
        <span className="chip neutral">{t.staged.actionCount(group.actions.length)}</span>
      </header>
      <div className="staged-action-stack">
        {group.actions.map((action) => (
          <StagedActionCard
            key={action.id}
            action={action}
            canWrite={canWriteAction(action)}
            busy={busy}
            history={history}
            demo={demo}
            initialAudit={demo ? auditFor(action) : undefined}
            stagedTest={stagedTests[action.id] ?? null}
            scope={submissionScope(action)}
            onPush={onPush}
            onDiscard={onDiscard}
          />
        ))}
      </div>
    </section>
  );
}

function StagedActionCard({
  action,
  canWrite,
  busy,
  history,
  demo,
  initialAudit,
  stagedTest,
  scope,
  onPush,
  onDiscard,
}: {
  action: OutboxAction;
  canWrite: boolean;
  busy: BusyAction | null;
  history: boolean;
  demo: boolean;
  initialAudit?: AuditEvent[];
  /** Server-projected ghost run for a staged test upload; null when none. */
  stagedTest: ComponentPreviewTest | null;
  scope: SubmissionScope;
  onPush: (action: OutboxAction) => Promise<void>;
  onDiscard: (action: OutboxAction) => Promise<void>;
}) {
  const pushing = busy?.id === action.id && busy.kind === "push";
  const discarding = busy?.id === action.id && busy.kind === "discard";
  // This is the complete server snapshot staged with the action. The worker
  // reconstructs and compares it before submission; the approval screen only
  // formats it and never derives a value from the raw ghost run.
  const stagedDerived =
    !history && isTestUpload(action)
      ? parseWorksheetDerived(action.payload.derived)
      : null;
  const hasReviewValues = stagedTest !== null || (stagedDerived?.steps.length ?? 0) > 0;
  const [audit, setAudit] = useState<AuditEvent[] | null>(initialAudit ?? null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  useEffect(() => {
    setAudit(demo ? (initialAudit ?? []) : null);
    setAuditLoading(false);
    setAuditError(null);
  }, [action.id, demo]);

  async function loadAudit(event: SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open || demo || audit !== null || auditLoading) return;
    setAuditLoading(true);
    setAuditError(null);
    try {
      setAudit(await getOutboxAudit(action.id));
    } catch (caught) {
      setAuditError(errorMessage(caught));
    } finally {
      setAuditLoading(false);
    }
  }

  return (
    <article className="staged-action-card">
      <div className="staged-action-summary">
        {/* The card is a two-column grid whose left column is this stack, so
            the proposed values live here rather than as a new grid child. */}
        <div>
          <strong>{summarizeAction(action)}</strong>
          <span className="mono muted">#{action.id} · {action.kind}</span>
          {stagedDerived !== null && <DerivedVerdicts derived={stagedDerived} />}
          {stagedTest !== null ? (
            <StagedValues test={stagedTest} />
          ) : (
            // Terminal uploads are past judging (their values live in the
            // mirrored run), so the gap is only worth naming while open.
            !history &&
            isTestUpload(action) &&
            !hasReviewValues && (
              <p className="staged-scope-hint">{t.staged.valuesUnavailable}</p>
            )
          )}
        </div>
        <span className={STATUS_CHIP[action.status]}>
          {t.components.previewStatuses[action.status]}
        </span>
      </div>
      {!history && !scope.submittable && (
        <p className="staged-scope-hint">
          {scope.reason === "not_dummy"
            ? t.staged.productionScopeHint
            : t.staged.scopeUnavailable}
        </p>
      )}
      {!history && !canWrite && <p className="staged-scope-hint">{t.staged.readOnlyHint}</p>}
      {!history && canWrite && (canPush(action.status) || canDiscard(action.status)) && (
        <div className="staged-card-actions">
          {scope.submittable && canPush(action.status) && (
            <button
              type="button"
              className="btn primary"
              disabled={busy !== null}
              onClick={() => void onPush(action)}
            >
              {pushing ? t.staged.pushing : t.staged.push}
            </button>
          )}
          {canDiscard(action.status) && (
            <button
              type="button"
              className="btn"
              disabled={busy !== null}
              onClick={() => void onDiscard(action)}
            >
              {discarding ? t.staged.discarding : t.staged.discard}
            </button>
          )}
        </div>
      )}
      <details className="staged-action-details" onToggle={(event) => void loadAudit(event)}>
        <summary>{t.staged.details}</summary>
        <dl className="staged-detail-grid">
          <div>
            <dt>{t.staged.attempts}</dt>
            <dd>{action.attempts}</dd>
          </div>
          <div>
            <dt>{t.staged.externalRef}</dt>
            <dd className="mono">{action.external_ref ?? t.common.none}</dd>
          </div>
          <div>
            <dt>{t.staged.createdBy}</dt>
            <dd>{action.created_by}</dd>
          </div>
          <div>
            <dt>{t.staged.created}</dt>
            <dd>{formatTimestamp(action.created_at)}</dd>
          </div>
          <div>
            <dt>{t.staged.updated}</dt>
            <dd>{formatTimestamp(action.updated_at)}</dd>
          </div>
          <div className="staged-detail-wide">
            <dt>{t.staged.error}</dt>
            <dd className={action.error === null ? "muted" : "error-text"}>
              {action.error ?? t.common.none}
            </dd>
          </div>
        </dl>
        {stagedTest !== null && <StagedValueList test={stagedTest} />}
        {stagedDerived !== null && (
          <DerivedDetail derived={stagedDerived} source="staged" />
        )}
        <div className="staged-audit">
          <div className="field-label">{t.staged.audit}</div>
          {auditLoading ? (
            <p className="muted">{t.common.loading}</p>
          ) : auditError !== null ? (
            <p className="error-text">{t.staged.auditUnavailable}: {auditError}</p>
          ) : audit === null ? (
            <p className="muted">{t.common.loading}</p>
          ) : audit.length === 0 ? (
            <p className="muted">{t.staged.noAudit}</p>
          ) : (
            <ol className="staged-audit-list">
              {audit.map((event) => (
                <li key={event.id}>
                  <div className="staged-audit-head">
                    <strong>{event.action}</strong>
                    <span>{event.actor}</span>
                    <time className="muted" dateTime={event.ts}>
                      {formatTimestamp(event.ts)}
                    </time>
                  </div>
                  {Object.keys(event.detail).length > 0 && (
                    <dl className="staged-audit-detail">
                      {Object.entries(event.detail).map(([key, value]) => (
                        <div key={key}>
                          <dt className="mono">{key}</dt>
                          <dd>{formatAuditValue(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      </details>
    </article>
  );
}

/**
 * The compact head of a staged measurement: test type, run identity, and the
 * proposed values under the worksheet's rules (first three scalars inline, the
 * rest as `+n`, arrays/maps as an extent chip). The `+n` chip is a hover title
 * only, so every value stays reachable without a pointer through
 * `StagedValueList` in the action details below.
 */
function StagedValues({ test }: { test: ComponentPreviewTest }) {
  const { scalars, arrays } = compactStagedValues(test);
  const inline = scalars.slice(0, INLINE_SCALARS);
  const rest = scalars.slice(INLINE_SCALARS);
  const propertyCount = Object.keys(test.properties ?? {}).length;
  const runText = runNumberText(test.run_number);
  const measuredText = measuredAtText(test.measured_at);

  return (
    <div className="staged-values" aria-label={t.staged.valuesRegionLabel(test.test_type)}>
      <div className="ws-values">
        <span className="chip neutral mono">{test.test_type}</span>
        {test.passed !== null && (
          <span className={test.passed ? "chip green" : "chip red"}>
            {test.passed ? t.testResults.passed : t.testResults.failed}
          </span>
        )}
        {runText !== null && <span className="ws-val">{runText}</span>}
        {measuredText !== null && <span className="ws-val">{measuredText}</span>}
        {propertyCount > 0 && (
          <span className="chip neutral">{t.staged.conditionCount(propertyCount)}</span>
        )}
      </div>
      {scalars.length === 0 && arrays.length === 0 ? (
        <p className="muted">{t.staged.valuesEmpty}</p>
      ) : (
        <div className="ws-values">
          {inline.map((scalar) => (
            <span className="ws-val" key={scalar.code} title={scalar.code}>
              <span className="ws-val-name">{scalar.name}</span>{" "}
              <span className="mono">{formatScalar(scalar.value)}</span>
            </span>
          ))}
          {rest.length > 0 && (
            <span className="chip neutral" title={scalarTitle(rest)}>
              {t.worksheet.moreValues(rest.length)}
            </span>
          )}
          {arrays.map((array) => (
            <span className="chip neutral mono" key={array.code} title={array.name}>
              {arraySummaryLabel(array)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Every staged value, keyboard-reachable inside the action details. Arrays and
 * maps stay counts here too — completeness must not become the number wall.
 */
function StagedValueList({ test }: { test: ComponentPreviewTest }) {
  const { scalars, arrays } = compactStagedValues(test);
  if (scalars.length === 0 && arrays.length === 0) return null;
  return (
    <div className="staged-audit">
      <div className="field-label">{t.staged.valuesLabel}</div>
      <dl className="staged-detail-grid">
        {scalars.map((scalar) => (
          <div key={`scalar:${scalar.code}`}>
            <dt title={scalar.code}>{scalar.name}</dt>
            <dd className="mono">{formatScalar(scalar.value)}</dd>
          </div>
        ))}
        {arrays.map((array) => (
          <div key={`array:${array.code}`}>
            <dt title={array.code}>{array.name}</dt>
            <dd className="mono">{arraySummaryLabel(array)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
