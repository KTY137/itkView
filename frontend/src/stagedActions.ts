import {
  postOutboxTransition,
  type OutboxAction,
  type OutboxStatus,
} from "./api";

const NEXT_PUSH_STATUS: Partial<Record<OutboxStatus, OutboxStatus>> = {
  draft: "validated",
  validated: "approved",
  approved: "submitted",
  failed: "submitted",
};

export function canPush(status: OutboxStatus): boolean {
  return status in NEXT_PUSH_STATUS;
}

export function canDiscard(status: OutboxStatus): boolean {
  return status === "draft" || status === "validated" || status === "approved" || status === "failed";
}

/**
 * Advance through the existing outbox state machine until the worker-owned
 * `submitted` state. Each transition is awaited, so an API rejection stops the
 * chain at the first failed boundary and leaves the server's last valid state
 * intact.
 */
export async function pushToPdb(action: OutboxAction, actor: string): Promise<OutboxAction> {
  let current = action;
  while (canPush(current.status)) {
    const target = NEXT_PUSH_STATUS[current.status];
    if (target === undefined) break;
    current = await postOutboxTransition(current.id, { to: target, actor });
  }
  return current;
}

export async function discardStagedAction(
  action: OutboxAction,
  actor: string,
): Promise<OutboxAction> {
  if (!canDiscard(action.status)) return action;
  return postOutboxTransition(action.id, { to: "cancelled", actor });
}

