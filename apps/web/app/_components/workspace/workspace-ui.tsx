"use client";

import { Check, ChevronDown, ChevronsDown, ChevronsUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

type UiLanguage = "zh-CN" | "en";
type InspectorCollection = "branches" | "relationships" | "inventory" | "threads" | "summaries" | "canon" | "memories";

export function uiText(language: UiLanguage, zh: string, en: string) {
  return language === "zh-CN" ? zh : en;
}

export function SelectMenu({
  className = "",
  icon: Icon,
  label,
  value,
  options,
  onChange,
  disabled = false,
  placeholder = "请选择"
}: {
  className?: string;
  icon: LucideIcon;
  label: string;
  value: string;
  options: Array<{ value: string; label: string; detail?: string; icon?: LucideIcon; disabled?: boolean }>;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);
  const SelectedIcon = selected?.icon ?? Icon;
  const hasOptionIcons = options.some((option) => option.icon);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`selectMenu ${className} ${hasOptionIcons ? "hasOptionIcons" : ""} ${open ? "open" : ""}`}>
      <button
        type="button"
        className="selectMenuTrigger"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <SelectedIcon size={14} />
        <span>{selected?.label ?? placeholder}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="selectMenuPopover" role="listbox" aria-label={label}>
          {options.map((option) => {
            const OptionIcon = option.icon;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                disabled={option.disabled}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                {OptionIcon && <i className="selectOptionIcon"><OptionIcon size={15} /></i>}
                <span>{option.label}</span>
                {option.detail && <small>{option.detail}</small>}
                {option.value === value && <Check className="selectOptionCheck" size={13} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Panel({ title, icon: Icon, action, count, children }: { title: string; icon?: LucideIcon; action?: ReactNode; count?: number; children: ReactNode }) {
  return (
    <section className="makePanel" aria-label={title}>
      <header>
        {Icon && <Icon size={14} />}
        <h3>{title}</h3>
        {typeof count === "number" && <span className="countBadge">{count}</span>}
        {action}
      </header>
      <div className="panelBody">{children}</div>
    </section>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "teal" | "amber" | "graphite" | "danger" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="emptyState">{children}</p>;
}

export function Stat({ label, value, icon: Icon, accent = "ink" }: { label: string; value: string; icon?: LucideIcon; accent?: "ink" | "teal" | "amber" }) {
  return (
    <div className="statTile">
      <div>{Icon && <Icon size={12} />}<span>{label}</span></div>
      <strong className={accent}>{value}</strong>
    </div>
  );
}

export function Meter({ value, tone = "teal" }: { value: number; tone?: "teal" | "amber" | "graphite" }) {
  const pct = Math.max(0, Math.min(100, value < 0 ? 50 + value / 2 : value));
  return <span className="meter"><i className={tone} style={{ width: `${pct}%` }} /></span>;
}

export function ProgressiveControls({
  uiLanguage,
  collection,
  total,
  visible,
  onMore,
  onCollapse
}: {
  uiLanguage: UiLanguage;
  collection: InspectorCollection;
  total: number;
  visible: number;
  onMore: (collection: InspectorCollection, total: number) => void;
  onCollapse: (collection: InspectorCollection) => void;
}) {
  if (total <= 3) return null;
  const shown = Math.min(total, visible);
  return (
    <div className="progressiveControls">
      <small>{shown} / {total}</small>
      <span />
      {shown > 3 && (
        <button className="cmdButton" type="button" onClick={() => onCollapse(collection)}>
          <ChevronsUp size={13} />{uiText(uiLanguage, "收起", "Collapse")}
        </button>
      )}
      {shown < total && (
        <button className="cmdButton" type="button" onClick={() => onMore(collection, total)}>
          <ChevronsDown size={13} />{uiText(uiLanguage, `再加载 ${Math.min(3, total - shown)} 条`, `Load ${Math.min(3, total - shown)} more`)}
        </button>
      )}
    </div>
  );
}

export function countWorldRules(rules: unknown) {
  if (Array.isArray(rules)) return rules.length;
  if (!rules || typeof rules !== "object") return 0;
  return Object.values(rules).reduce((total, value) => total + (Array.isArray(value) ? value.length : 1), 0);
}

export function formatStoryUpdated(value: string, uiLanguage: UiLanguage = "zh-CN") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || uiText(uiLanguage, "刚刚", "just now");
  return new Intl.DateTimeFormat(uiLanguage === "zh-CN" ? "zh-CN" : "en-AU", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function normalizeImportance(value: number) {
  if (!Number.isFinite(value)) return 5;
  return Math.max(1, Math.min(10, Math.round(value)));
}

export function Telemetry({ label, value, icon: Icon }: { label: string; value: string; icon?: LucideIcon }) {
  return (
    <div className="telemetry">
      <dt>{Icon && <Icon size={11} />} {label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function TabButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return <button type="button" className={active ? "active" : ""} onClick={onClick} aria-label={label}><Icon size={14} /><span>{label}</span></button>;
}

export function IconToggle({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return <button className={`iconToggle ${active ? "active" : ""}`} onClick={onClick} aria-label={label} title={label}><Icon size={15} /></button>;
}

export function MobileTabButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return <button className={active ? "active" : ""} onClick={onClick} aria-label={label}><Icon size={18} /><span>{label}</span></button>;
}

export function CommandButton({ icon: Icon, label, primary = false, compact = false, disabled = false, onClick }: { icon: LucideIcon; label: string; primary?: boolean; compact?: boolean; disabled?: boolean; onClick?: () => void }) {
  return <button className={`cmdButton ${primary ? "primary" : ""} ${compact ? "compact" : ""}`} disabled={disabled} onClick={onClick} aria-label={label} title={label}><Icon size={compact ? 11 : 13} /><span>{label}</span></button>;
}
