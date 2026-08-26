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
  OutboxAction,
  OutboxStatus,
} from "../api";
import { useAuth } from "../auth";
import { filterDemoComponents, makeDemoOutbox } from "../demoData";
import { formatTimestamp, t } from "../i18n";
import {
  canDiscard,
  canPush,
  discardStagedAction,
  pushToPdb,
} from "../stagedActions";
import { stageChipClass, stageLabel } from "../ui";

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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  const [previewActions, setPreviewActions] = useState<Record<number, ComponentPreviewAction>>({});
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
      for (const result of previewResults) {
        if (result.status !== "fulfilled") continue;
        for (const action of result.value.staged_actions) metadata[action.id] = action;
      }
      setPreviewActions(metadata);
    } catch (caught) {
      if (caught instanceof ApiError && caught.isNetwork) {
        if (demoStore.current === null) demoStore.current = makeDemoOutbox();
        const demoActions = demoStore.current;
        setActions(demoActions);
        setComponents(filterDemoComponents("", "", ""));
        setThumbnails({});
        setPreviewActions({});
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
  thumbnails: Record<string, string>;
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
            className="staged-component-thumb"
            src={componentAttachmentUrl(group.sn, thumbnail)}
            alt={t.staged.thumbnailAlt(group.localName)}
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
  scope: SubmissionScope;
  onPush: (action: OutboxAction) => Promise<void>;
  onDiscard: (action: OutboxAction) => Promise<void>;
}) {
  const pushing = busy?.id === action.id && busy.kind === "push";
  const discarding = busy?.id === action.id && busy.kind === "discard";
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
        <div>
          <strong>{summarizeAction(action)}</strong>
          <span className="mono muted">#{action.id} · {action.kind}</span>
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
