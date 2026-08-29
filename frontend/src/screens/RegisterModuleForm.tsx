// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-34c4d8d19cdd
import { useState } from "react";
import type { FormEvent } from "react";
import { postComponentRegister } from "../api";
import type { Institute } from "../api";
import { t } from "../i18n";

// Collaboration-wide registrable types (mirrors the backend allowlist). Sensors
// and ASICs are deliberately absent — they are never registered (hard rule #2).
const REGISTRABLE_TYPES = ["MODULE", "HYBRID"];

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Register a DUMMY module/hybrid as a reviewed outbox draft (docs/10). The form
 * only offers the registrable types; the backend refuses anything else, and the
 * real PDB write stays gated by the dummy-only scope. Result is a draft in the
 * Outbox, never a direct production write.
 */
export default function RegisterModuleForm({
  institutes,
  defaultInstitute,
  onDone,
}: {
  institutes: Institute[];
  defaultInstitute: string;
  onDone: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [componentType, setComponentType] = useState("MODULE");
  const [typeCode, setTypeCode] = useState("");
  const [localName, setLocalName] = useState("");
  const [institute, setInstitute] = useState(defaultInstitute);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const inst = institute || defaultInstitute;
    if (inst === "") {
      setError(t.register.needsInstitute);
      return;
    }
    if (typeCode.trim() === "") return;
    setBusy(true);
    try {
      const draft = await postComponentRegister({
        component_type: componentType,
        type_code: typeCode.trim(),
        institute_code: inst,
        local_name: localName.trim() || undefined,
      });
      onDone(t.register.created(draft.id));
      setTypeCode("");
      setLocalName("");
      setOpen(false);
    } catch (err) {
      setError(`${t.register.failed}: ${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        ＋ {t.register.title}
      </button>
    );
  }

  return (
    <form className="toolbar create-institute-form" onSubmit={(e) => void handleSubmit(e)}>
      <select
        className="select-input"
        value={componentType}
        onChange={(e) => setComponentType(e.target.value)}
        aria-label={t.register.typeLabel}
      >
        {REGISTRABLE_TYPES.map((ty) => (
          <option key={ty} value={ty}>
            {ty}
          </option>
        ))}
      </select>
      <input
        className="short-input mono"
        value={typeCode}
        onChange={(e) => setTypeCode(e.target.value.toUpperCase())}
        placeholder={t.register.typeCodePlaceholder}
        aria-label={t.register.typeCodeLabel}
        maxLength={32}
        required
      />
      <input
        className="text-input"
        value={localName}
        onChange={(e) => setLocalName(e.target.value)}
        placeholder={t.register.localNamePlaceholder}
        aria-label={t.register.localNameLabel}
        maxLength={64}
      />
      {institutes.length > 1 && (
        <select
          className="select-input"
          value={institute}
          onChange={(e) => setInstitute(e.target.value)}
          aria-label={t.components.instituteLabel}
        >
          {institutes.map((i) => (
            <option key={i.code} value={i.code}>
              {i.code}
            </option>
          ))}
        </select>
      )}
      <button className="btn primary" disabled={busy}>
        {busy ? t.register.submitting : t.register.submit}
      </button>
      <button type="button" className="btn" onClick={() => setOpen(false)}>
        {t.common.cancel}
      </button>
      <span className="muted">{t.register.onlyDummy}</span>
      {error !== null && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
        </div>
      )}
    </form>
  );
}
