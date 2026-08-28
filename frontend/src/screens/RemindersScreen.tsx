import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  acknowledgeReminderOccurrence,
  ApiError,
  deleteReminder,
  getNotificationChannels,
  getReminderOccurrences,
  getReminders,
  patchReminder,
  postNotificationTest,
  postReminder,
} from "../api";
import type {
  NotificationChannel,
  Reminder,
  ReminderOccurrence,
  ReminderScheduleKind,
} from "../api";
import { useAuth } from "../auth";
import { makeDemoNotificationChannels, makeDemoReminders } from "../demoData";
import { formatRelative, formatTimestamp, parseApiTimestamp, t } from "../i18n";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const SCHEDULES: ReminderScheduleKind[] = ["once", "daily", "weekly", "monthly"];

function scheduleLabel(kind: ReminderScheduleKind): string {
  if (kind === "daily") return t.reminders.scheduleDaily;
  if (kind === "weekly") return t.reminders.scheduleWeekly;
  if (kind === "monthly") return t.reminders.scheduleMonthly;
  return t.reminders.scheduleOnce;
}

/**
 * Recurring site tasks ("clean the flow bench") that the background worker
 * posts to the institute's notification channels. The channel list here is
 * secret-free — names and kinds only, webhook URLs never reach the browser.
 */
export default function RemindersScreen() {
  const { canWrite, isAdmin, demo: demoSession, showToast } = useAuth();
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [occurrences, setOccurrences] = useState<ReminderOccurrence[]>([]);
  const [occurrencesLoading, setOccurrencesLoading] = useState(true);
  const [occurrencesError, setOccurrencesError] = useState<string | null>(null);
  const [acknowledgingId, setAcknowledgingId] = useState<number | null>(null);

  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [channelsFailed, setChannelsFailed] = useState<string | null>(null);
  const [testingChannel, setTestingChannel] = useState<string | null>(null);

  // Create-panel form state.
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [channel, setChannel] = useState("");
  const [schedule, setSchedule] = useState<ReminderScheduleKind>("weekly");
  const [firstDue, setFirstDue] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Per-row action state so pause/resume/delete cannot be double-fired.
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    getReminders(undefined, ctrl.signal)
      .then((data) => {
        setReminders(data);
        setDemo(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setReminders(makeDemoReminders());
          setDemo(true);
        } else {
          setError(errorMessage(err));
        }
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [reloadKey]);

  useEffect(() => {
    const ctrl = new AbortController();
    setOccurrencesLoading(true);
    setOccurrencesError(null);
    getReminderOccurrences(true, undefined, ctrl.signal)
      .then((data) => {
        setOccurrences(data);
        setOccurrencesLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setOccurrences([]);
        } else {
          setOccurrencesError(errorMessage(err));
        }
        setOccurrencesLoading(false);
      });
    return () => ctrl.abort();
  }, [reloadKey]);

  useEffect(() => {
    const ctrl = new AbortController();
    setChannelsFailed(null);
    getNotificationChannels(ctrl.signal)
      .then((data) => setChannels(data))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) {
          setChannels(makeDemoNotificationChannels());
        } else {
          // e.g. a viewer without an institute — fall back to an empty list and
          // keep the failure visible as a note instead of blocking the screen.
          setChannels([]);
          setChannelsFailed(errorMessage(err));
        }
      });
    return () => ctrl.abort();
  }, [reloadKey]);

  const offlineWrites = demo || demoSession;

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const cleanTitle = title.trim();
    if (cleanTitle === "" || firstDue === "") {
      setFormError(t.reminders.formIncomplete);
      return;
    }
    if (offlineWrites) {
      // Demo mode: nothing to persist — acknowledge and reset, same as the
      // other screens' demo-write pattern.
      showToast(t.reminders.created(cleanTitle));
      resetForm();
      return;
    }
    setCreating(true);
    try {
      const cleanNote = note.trim();
      await postReminder({
        title: cleanTitle,
        note: cleanNote === "" ? undefined : cleanNote,
        channel: channel === "" ? undefined : channel,
        schedule_kind: schedule,
        next_due_at: new Date(firstDue).toISOString(),
      });
      showToast(t.reminders.created(cleanTitle));
      resetForm();
      setReloadKey((key) => key + 1);
    } catch (err) {
      setFormError(`${t.reminders.createFailed}: ${errorMessage(err)}`);
    } finally {
      setCreating(false);
    }
  }

  function resetForm() {
    setTitle("");
    setNote("");
    setChannel("");
    setSchedule("weekly");
    setFirstDue("");
  }

  async function handleToggle(reminder: Reminder) {
    setBusyId(reminder.id);
    try {
      if (offlineWrites) {
        setReminders((current) =>
          current.map((item) =>
            item.id === reminder.id ? { ...item, active: !item.active } : item,
          ),
        );
        return;
      }
      const updated = await patchReminder(reminder.id, { active: !reminder.active });
      setReminders((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (err) {
      showToast(`${t.reminders.updateFailed}: ${errorMessage(err)}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(reminder: Reminder) {
    setBusyId(reminder.id);
    try {
      if (!offlineWrites) await deleteReminder(reminder.id);
      setReminders((current) => current.filter((item) => item.id !== reminder.id));
      showToast(t.reminders.deleted);
    } catch (err) {
      showToast(`${t.reminders.deleteFailed}: ${errorMessage(err)}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleTest(name: string) {
    setTestingChannel(name);
    try {
      if (!offlineWrites) await postNotificationTest(name);
      showToast(t.reminders.testSent(name));
    } catch (err) {
      showToast(`${t.reminders.testFailed}: ${errorMessage(err)}`);
    } finally {
      setTestingChannel(null);
    }
  }

  async function handleAcknowledge(occurrence: ReminderOccurrence) {
    setAcknowledgingId(occurrence.id);
    try {
      if (!offlineWrites) await acknowledgeReminderOccurrence(occurrence.id);
      setOccurrences((current) => current.filter((item) => item.id !== occurrence.id));
      showToast(t.reminders.occurrenceAcknowledged);
    } catch (err) {
      showToast(`${t.reminders.occurrenceAckFailed}: ${errorMessage(err)}`);
    } finally {
      setAcknowledgingId(null);
    }
  }

  const now = Date.now();

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.reminders}</h1>
        <span className="sub">{t.reminders.subtitle}</span>
        {demo && <span className="badge warn">{t.common.demoBadge}</span>}
      </div>

      {error !== null ? (
        <div className="error-banner" role="alert">
          <span>
            {t.reminders.loadError}: {error}
          </span>
          <button
            type="button"
            className="btn"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            {t.common.retry}
          </button>
        </div>
      ) : loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : reminders.length === 0 ? (
        <p className="state-note">{t.reminders.empty}</p>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t.reminders.colTitle}</th>
                <th scope="col">{t.reminders.colSchedule}</th>
                <th scope="col">{t.reminders.colNextDue}</th>
                <th scope="col">{t.reminders.colChannel}</th>
                <th scope="col">{t.reminders.colLastFired}</th>
                <th scope="col">{t.reminders.colStatus}</th>
                {canWrite && <th scope="col" />}
              </tr>
            </thead>
            <tbody>
              {reminders.map((reminder) => {
                const busy = busyId === reminder.id;
                const overdue =
                  reminder.active &&
                  parseApiTimestamp(reminder.next_due_at).getTime() < now;
                return (
                  <tr key={reminder.id}>
                    <td>
                      <div>{reminder.title}</div>
                      {reminder.note !== null && reminder.note !== "" && (
                        <div className="muted phase4-table-note">{reminder.note}</div>
                      )}
                    </td>
                    <td>{scheduleLabel(reminder.schedule_kind)}</td>
                    <td>
                      <div className="row-actions">
                        <span className="mono">
                          {formatTimestamp(reminder.next_due_at)}
                        </span>
                        {overdue && (
                          <span className="chip amber">
                            {formatRelative(reminder.next_due_at)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      {reminder.channel !== null && reminder.channel !== "" ? (
                        reminder.channel
                      ) : (
                        <span className="muted">{t.reminders.noChannel}</span>
                      )}
                    </td>
                    <td>
                      <div className="row-actions">
                        <span className="muted">
                          {reminder.last_fired_at !== null
                            ? formatRelative(reminder.last_fired_at)
                            : t.reminders.neverFired}
                        </span>
                        {reminder.last_error !== null && (
                          <span className="chip red" title={reminder.last_error}>
                            {t.reminders.lastErrorPrefix}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className={reminder.active ? "chip green" : "chip muted"}>
                        {reminder.active
                          ? t.reminders.statusActive
                          : t.reminders.statusPaused}
                      </span>
                    </td>
                    {canWrite && (
                      <td>
                        <div className="row-actions phase4-actions-end">
                          <button
                            type="button"
                            className="btn"
                            disabled={busy}
                            onClick={() => void handleToggle(reminder)}
                          >
                            {reminder.active
                              ? t.reminders.pauseBtn
                              : t.reminders.resumeBtn}
                          </button>
                          <button
                            type="button"
                            className="btn danger"
                            disabled={busy}
                            onClick={() => void handleDelete(reminder)}
                          >
                            {t.reminders.deleteBtn}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {canWrite && (
        <form
          className="panel compact-panel phase4-form"
          onSubmit={(event) => void handleCreate(event)}
        >
          <h2 className="section-title">{t.reminders.addTitle}</h2>
          <div className="phase4-form-grid">
            <Field label={t.reminders.titleFieldLabel}>
              <input
                className="text-input"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={t.reminders.titlePlaceholder}
                required
              />
            </Field>
            <Field label={t.reminders.noteFieldLabel} wide>
              <textarea
                className="phase4-textarea"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={2}
              />
            </Field>
            <Field label={t.reminders.channelFieldLabel}>
              <select
                className="select-input"
                value={channel}
                onChange={(event) => setChannel(event.target.value)}
              >
                <option value="">{t.reminders.noChannel}</option>
                {channels.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name} ({item.kind})
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t.reminders.scheduleFieldLabel}>
              <select
                className="select-input"
                value={schedule}
                onChange={(event) =>
                  setSchedule(event.target.value as ReminderScheduleKind)
                }
              >
                {SCHEDULES.map((kind) => (
                  <option key={kind} value={kind}>
                    {scheduleLabel(kind)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t.reminders.firstDueFieldLabel}>
              <input
                className="text-input"
                type="datetime-local"
                value={firstDue}
                onChange={(event) => setFirstDue(event.target.value)}
                required
              />
            </Field>
          </div>
          {formError !== null && (
            <div className="error-banner" role="alert">
              <span>{formError}</span>
            </div>
          )}
          <div className="phase4-form-actions">
            <button type="submit" className="btn primary" disabled={creating}>
              {creating ? t.common.loading : t.reminders.addBtn}
            </button>
          </div>
        </form>
      )}

      <section
        className="panel compact-panel phase4-form"
        aria-labelledby="open-reminder-tasks-title"
      >
        <h2 className="section-title" id="open-reminder-tasks-title">
          {t.reminders.openTasksTitle}
        </h2>
        <p className="muted phase4-copy">{t.reminders.openTasksHint}</p>
        {occurrencesLoading ? (
          <p className="state-note">{t.common.loading}</p>
        ) : occurrencesError !== null ? (
          <div className="error-banner" role="alert">
            <span>
              {t.reminders.openTasksLoadFailed}: {occurrencesError}
            </span>
            <button
              type="button"
              className="btn"
              onClick={() => setReloadKey((key) => key + 1)}
            >
              {t.common.retry}
            </button>
          </div>
        ) : occurrences.length === 0 ? (
          <p className="state-note">{t.reminders.openTasksEmpty}</p>
        ) : (
          <div className="phase4-channel-list">
            {occurrences.map((occurrence) => {
              const reminder = reminders.find((item) => item.id === occurrence.reminder_id);
              const deliveryFailed = occurrence.delivery_status === "failed";
              const escalated = occurrence.escalated_at !== null;
              return (
                <div className="phase4-channel" key={occurrence.id}>
                  <div>
                    <div>{reminder?.title ?? t.reminders.deletedReminder}</div>
                    <div className="muted phase4-table-note">
                      {t.reminders.taskFired(formatRelative(occurrence.fired_at))}
                    </div>
                  </div>
                  <span className={deliveryFailed ? "chip red" : "chip neutral"}>
                    {deliveryFailed
                      ? t.reminders.deliveryFailed
                      : occurrence.delivery_status === "sent"
                        ? t.reminders.deliverySent
                        : t.reminders.deliveryAuditOnly}
                  </span>
                  {escalated && (
                    <span className="chip amber">{t.reminders.escalated}</span>
                  )}
                  {canWrite && (
                    <button
                      type="button"
                      className="btn primary"
                      disabled={acknowledgingId !== null}
                      onClick={() => void handleAcknowledge(occurrence)}
                    >
                      {acknowledgingId === occurrence.id
                        ? t.common.loading
                        : t.reminders.acknowledgeBtn}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section
        className="panel compact-panel phase4-form"
        aria-labelledby="reminder-channels-title"
      >
        <h2 className="section-title" id="reminder-channels-title">
          {t.reminders.channelsTitle}
        </h2>
        <p className="muted phase4-copy">{t.reminders.channelsHint}</p>
        {channels.length === 0 ? (
          <p className="state-note">
            {channelsFailed !== null
              ? `${t.reminders.channelsLoadFailed}: ${channelsFailed}`
              : t.reminders.channelsEmpty}
          </p>
        ) : (
          <div className="phase4-channel-list">
            {channels.map((item) => (
              <div className="phase4-channel" key={item.name}>
                <span className="mono">{item.name}</span>
                <span className="chip neutral">{item.kind}</span>
                {isAdmin && canWrite && (
                  <button
                    type="button"
                    className="btn"
                    disabled={testingChannel !== null}
                    onClick={() => void handleTest(item.name)}
                  >
                    {testingChannel === item.name
                      ? t.common.loading
                      : t.reminders.testBtn}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <p className="muted phase4-copy">{t.reminders.workerHint}</p>
    </div>
  );
}

function Field({
  label,
  children,
  wide,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={wide === true ? "phase4-field phase4-field-wide" : "phase4-field"}>
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}
