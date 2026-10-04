import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { Icon } from "./Icon";

export type ToastTone = "success" | "danger" | "info";

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

type Notify = (tone: ToastTone, message: string) => void;

const ToastContext = createContext<Notify | null>(null);

const DISMISS_MS: Record<ToastTone, number> = { success: 5000, info: 5000, danger: 9000 };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback<Notify>(
    (tone, message) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-3), { id, tone, message }]);
      setTimeout(() => dismiss(id), DISMISS_MS[tone]);
    },
    [dismiss],
  );

  const value = useMemo(() => notify, [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.tone}`}>
            <span>{toast.message}</span>
            <button
              type="button"
              className="icon-button icon-button--small"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss"
            >
              <Icon name="close" size={13} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): Notify {
  const notify = useContext(ToastContext);
  if (!notify) throw new Error("useToast must be used inside <ToastProvider>");
  return notify;
}
