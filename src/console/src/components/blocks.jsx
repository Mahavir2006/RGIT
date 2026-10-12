// Shared layout blocks on top of the primitives. Thin enough that views stay readable,
// strict enough that spacing, borders and type sizes cannot drift per route.
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Inbox, Lock, RefreshCw, Info } from 'lucide-react';
import { Card, CardContent, Button, Input, Badge, Skeleton, StatusDot, StatusLabel } from '@/components/ui';
import { cn } from '@/lib/utils';

export const fade = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } }
};

export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04 } }
};

export function Panel({ title, description, actions, children, className = '', bodyClassName = '', ...rest }) {
  return (
    <motion.section variants={fade} className={cn('rounded-app border border-border bg-surface', className)} {...rest}>
      {(title || actions) && (
        <header className="flex items-center gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-[14px] font-semibold text-fg">{title}</h2>}
            {description && <p className="mt-0.5 text-[12.5px] text-fg-subtle">{description}</p>}
          </div>
          {actions && <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn('p-4', bodyClassName)}>{children}</div>
    </motion.section>
  );
}

export function Metric({ label, value, tone, hint }) {
  return (
    <div title={hint}>
      <div className="text-[12px] text-fg-subtle">{label}</div>
      <div className={cn('mt-1 text-[20px] font-semibold tabular-nums', tone === 'critical' ? 'text-critical' : tone === 'healthy' ? 'text-healthy' : tone === 'degraded' ? 'text-degraded' : 'text-fg')}>
        {value}
      </div>
    </div>
  );
}

// Three confidence dimensions are always separate, never blended into one trust badge.
export function ConfidenceBar({ label, value, hint, calibration }) {
  const tone = value >= 0.75 ? 'bg-healthy' : value >= 0.5 ? 'bg-degraded' : 'bg-critical';
  const text = value >= 0.75 ? 'text-healthy' : value >= 0.5 ? 'text-degraded' : 'text-critical';
  return (
    <div className="py-1.5" title={hint}>
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-[12.5px] text-fg-muted">{label}</span>
        <span className={cn('text-[13px] font-medium tabular-nums', text)}>{value.toFixed(2)}</span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3">
        <motion.div
          className={cn('h-full rounded-full', tone)}
          initial={{ width: 0 }}
          animate={{ width: `${Math.round(value * 100)}%` }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
      {calibration && <div className="mt-1 text-[11.5px] text-degraded">{calibration}</div>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist">
      {tabs.map(tab => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            'relative shrink-0 px-3 py-2 text-[13px] transition-colors',
            active === tab.id ? 'font-medium text-fg' : 'text-fg-muted hover:text-fg'
          )}
        >
          {tab.label}
          {tab.count !== undefined && <span className="ml-1.5 text-[12px] text-fg-subtle tabular-nums">{tab.count}</span>}
          {active === tab.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-t bg-accent" />}
        </button>
      ))}
    </div>
  );
}

export function Chips({ options, value, onChange, ariaLabel }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
      {options.map(option => {
        const key = typeof option === 'string' ? option : option.value ?? option.id;
        const label = typeof option === 'string' ? option : option.label;
        const on = Array.isArray(value) ? value.includes(key) : value === key;
        return (
          <button
            key={key}
            aria-pressed={on}
            onClick={() => onChange(key)}
            className={cn(
              'h-7 rounded-[6px] border px-2.5 text-[12.5px] transition-colors',
              on ? 'border-accent/40 bg-accent-soft font-medium text-accent' : 'border-border text-fg-muted hover:border-border-strong hover:text-fg'
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function DataTable({ columns, rows, onRowClick, selectedId, rowId, empty, maxHeight }) {
  if (!rows.length) return empty || <EmptyState title="Nothing here" body="No records match the current filters." />;
  return (
    <div className={cn('overflow-x-auto', maxHeight && 'overflow-y-auto')} style={maxHeight ? { maxHeight } : undefined}>
      <table className="w-full min-w-[720px] border-collapse">
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-border">
            {columns.map(column => (
              <th
                key={column.key}
                className={cn(
                  'px-4 py-2 text-[12px] font-medium text-fg-subtle',
                  column.align === 'right' ? 'text-right' : 'text-left'
                )}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr
              key={rowId ? rowId(row) : row.id}
              tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={event => {
                if (onRowClick && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onRowClick(row); }
              }}
              className={cn(
                'border-b border-border transition-colors last:border-0',
                onRowClick && 'cursor-pointer hover:bg-surface-2',
                selectedId && rowId && rowId(row) === selectedId && 'bg-accent-soft'
              )}
            >
              {columns.map(column => (
                <td key={column.key} className={cn('px-4 py-2.5 align-top text-[13px]', column.align === 'right' && 'text-right tabular-nums')}>
                  {column.render ? column.render(row) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- Global UI states -------------------------------------------------------------
export function LoadingState({ rows = 5, label = 'Loading' }) {
  return (
    <div className="space-y-2 p-1" role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <p className="pt-1 text-[12.5px] text-fg-subtle">
        Values are held back rather than flashed as zero while this loads.
      </p>
    </div>
  );
}

export function EmptyState({ title = 'Nothing here', body, action, icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Icon className="size-5 text-fg-subtle" />
      <div className="text-[13px] font-medium text-fg">{title}</div>
      {body && <p className="max-w-[48ch] text-[12.5px] leading-snug text-fg-muted">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ title = 'Request failed', message, requestId, onRetry }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center" role="alert">
      <AlertTriangle className="size-5 text-critical" />
      <div className="text-[13px] font-medium text-critical">{title}</div>
      <p className="max-w-[48ch] text-[12.5px] leading-snug text-fg-muted">{message}</p>
      {requestId && <code className="font-mono text-[11.5px] text-fg-subtle">request_id: {requestId}</code>}
      {onRetry && <Button size="sm" onClick={onRetry}><RefreshCw />Retry safely</Button>}
    </div>
  );
}

export function PermissionDenied({ missing }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center" role="alert">
      <Lock className="size-4 text-fg-subtle" />
      <div className="text-[13px] font-medium text-fg">Permission required</div>
      <p className="max-w-[44ch] text-[12.5px] leading-snug text-fg-muted">
        Your role cannot access {missing}. The underlying record is not shown, and no restricted data is disclosed here.
      </p>
    </div>
  );
}

export function Note({ children, tone = 'neutral', icon: Icon = Info }) {
  const tones = {
    neutral: 'border-border bg-surface-2 text-fg-muted',
    warning: 'border-degraded/25 bg-degraded-soft text-degraded',
    critical: 'border-critical/25 bg-critical-soft text-critical'
  };
  return (
    <div className={cn('flex items-start gap-2 rounded-[8px] border px-3 py-2.5 text-[12.5px] leading-snug', tones[tone])}>
      <Icon className="mt-0.5 size-3.5 shrink-0 opacity-70" />
      <p>{children}</p>
    </div>
  );
}

// Scores are heuristic rankings. This note must sit wherever they are displayed.
export function UncalibratedNote() {
  return (
    <Note tone="warning" icon={AlertTriangle}>
      Heuristic ranking, not a calibrated probability. Values are not comparable across incidents until
      evaluated against labelled data.
    </Note>
  );
}

export function Field({ label, value, onChange, options, type = 'select', placeholder, error, id }) {
  const fieldId = id || `f-${label.replace(/\W+/g, '-').toLowerCase()}`;
  return (
    <div>
      <label htmlFor={fieldId} className="mb-1.5 block text-[12.5px] font-medium text-fg-muted">{label}</label>
      {type === 'select' ? (
        <select
          id={fieldId}
          className={cn('h-8 w-full rounded-[6px] border border-border bg-surface px-2.5 text-[13px] text-fg focus:border-accent focus:outline-none', error && 'border-critical')}
          value={value}
          onChange={event => onChange(event.target.value)}
        >
          {options.map(option => {
            const optionValue = option.value ?? option;
            return <option key={optionValue} value={optionValue}>{option.label ?? optionValue}</option>;
          })}
        </select>
      ) : (
        <Input
          id={fieldId}
          type={type}
          value={value}
          placeholder={placeholder}
          onChange={event => onChange(event.target.value)}
          aria-invalid={error ? 'true' : undefined}
          className={error ? 'border-critical' : undefined}
        />
      )}
      {error && <p className="mt-1 text-[12px] text-critical">{error}</p>}
    </div>
  );
}

export function TextArea({ label, value, onChange, rows = 3, placeholder, disabled }) {
  const id = `t-${label.replace(/\W+/g, '-').toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[12.5px] font-medium text-fg-muted">{label}</label>
      <textarea
        id={id}
        rows={rows}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={event => onChange(event.target.value)}
        className="w-full resize-y rounded-[6px] border border-border bg-surface px-2.5 py-2 text-[13px] leading-snug text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
      />
    </div>
  );
}

export { Card, CardContent, Button, Badge, Input, Skeleton, StatusDot, StatusLabel, AnimatePresence };