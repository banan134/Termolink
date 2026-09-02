import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import s from "./ui.module.css";

// ---------- Button ----------
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  loading?: boolean;
};

export function Button({
  variant = "primary",
  loading = false,
  children,
  disabled,
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`${s.button} ${s[variant]} ${className ?? ""}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className={s.spinner} aria-hidden="true" />}
      {children}
    </button>
  );
}

// ---------- Field ----------
type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  help?: string;
  error?: string | string[];
};

export function Field({ label, help, error, id, className, ...rest }: FieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const errors = Array.isArray(error) ? error : error ? [error] : [];
  const describedBy = [help ? `${inputId}-help` : null, errors.length ? `${inputId}-err` : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={`${s.field} ${className ?? ""}`}>
      <label className={s.label} htmlFor={inputId}>
        {label}
      </label>
      <input
        id={inputId}
        className={`${s.input} ${errors.length ? s.inputError : ""}`}
        aria-invalid={errors.length ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...rest}
      />
      {help && (
        <span id={`${inputId}-help`} className={s.help}>
          {help}
        </span>
      )}
      {errors.map((e) => (
        <span key={e} id={`${inputId}-err`} className={s.errorText} role="alert">
          {e}
        </span>
      ))}
    </div>
  );
}

// ---------- Card ----------
export function Card({
  title,
  children,
  className,
  id,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`${s.card} ${className ?? ""}`}>
      {title && <h2 className={s.cardTitle}>{title}</h2>}
      {children}
    </section>
  );
}

// ---------- Chip ----------
export function Chip({
  tone = "neutral",
  children,
}: {
  tone?: "ok" | "off" | "read" | "ctrl" | "neutral";
  children: ReactNode;
}) {
  return <span className={`${s.chip} ${s[tone]}`}>{children}</span>;
}

// ---------- Alert ----------
export function Alert({
  tone = "info",
  children,
}: {
  tone?: "error" | "ok" | "info" | "warn";
  children: ReactNode;
}) {
  const cls = { error: s.alertError, ok: s.alertOk, info: s.alertInfo, warn: s.alertWarn }[tone];
  return (
    <div className={`${s.alert} ${cls}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

// ---------- Skeleton / EmptyState ----------
export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: string }) {
  return <div className={s.skeleton} style={{ height, width }} aria-hidden="true" />;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={s.empty}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <code className={s.mono}>{children}</code>;
}
