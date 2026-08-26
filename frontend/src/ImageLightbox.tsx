import { useEffect, useRef } from "react";

import { componentAttachmentUrl, type TestRunAttachment } from "./api";
import { t } from "./i18n";

export default function ImageLightbox({
  sn,
  attachment,
  onClose,
}: {
  sn: string;
  attachment: TestRunAttachment;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const label = attachment.title ?? attachment.filename ?? attachment.code;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    closeRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable === undefined || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, []);

  return (
    <div
      ref={dialogRef}
      className="img-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <button
        ref={closeRef}
        type="button"
        className="img-lightbox-close"
        aria-label={t.images.close}
        onClick={onClose}
      >
        ×
      </button>
      <img
        src={componentAttachmentUrl(sn, attachment.code)}
        alt={attachment.title ?? attachment.filename ?? t.images.untitled}
      />
      <div className="img-lightbox-cap">
        {attachment.test_type} · {label}
      </div>
    </div>
  );
}
