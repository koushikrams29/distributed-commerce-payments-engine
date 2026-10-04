import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  /** Destructive or hard-to-undo actions get the danger style. */
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** A modal confirmation on the native <dialog>: focus trapping and Escape come for free. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="confirm-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
      onClick={(event) => {
        // A click on the backdrop lands on the <dialog> element itself.
        if (event.target === ref.current && !busy) onCancel();
      }}
    >
      <div className="dialog__body">
        <h2 id="confirm-title" className="dialog__title">
          {title}
        </h2>
        <div className="dialog__content">{children}</div>
        <div className="dialog__actions">
          <button className="button button--secondary" type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className={danger ? "button button--danger" : "button"}
            type="button"
            onClick={onConfirm}
            disabled={busy}
            autoFocus
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
