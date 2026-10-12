// shadcn/ui-style primitives. Variants live in cva so tone stays consistent across the
// console and every colour still resolves to a token rather than a literal.
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] text-[13px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-accent-fg hover:bg-accent-hover',
        default: 'bg-surface text-fg border border-border hover:bg-surface-2 hover:border-border-strong',
        ghost: 'text-fg-muted hover:bg-surface-2 hover:text-fg',
        danger: 'text-critical border border-critical/30 bg-critical-soft hover:bg-critical hover:text-accent-fg'
      },
      size: {
        sm: 'h-7 px-2.5 text-[12.5px]',
        md: 'h-8 px-3',
        lg: 'h-9 px-4',
        icon: 'size-8 p-0',
        iconSm: 'size-7 p-0'
      }
    },
    defaultVariants: { variant: 'default', size: 'md' }
  }
);

export function Button({ className, variant, size, asChild = false, ...props }) {
  const Component = asChild ? Slot : 'button';
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-[5px] border px-1.5 py-0.5 text-[11.5px] font-medium',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-surface-2 text-fg-muted',
        accent: 'border-accent/25 bg-accent-soft text-accent',
        healthy: 'border-healthy/25 bg-healthy-soft text-healthy',
        degraded: 'border-degraded/25 bg-degraded-soft text-degraded',
        critical: 'border-critical/25 bg-critical-soft text-critical'
      }
    },
    defaultVariants: { tone: 'neutral' }
  }
);

export function Badge({ className, tone, ...props }) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export function Card({ className, ...props }) {
  return <div className={cn('rounded-app border border-border bg-surface', className)} {...props} />;
}

export function CardHeader({ className, ...props }) {
  return <div className={cn('flex items-center gap-2 px-4 py-3 border-b border-border', className)} {...props} />;
}

export function CardTitle({ className, ...props }) {
  return <h2 className={cn('text-[13px] font-semibold text-fg', className)} {...props} />;
}

export function CardDescription({ className, ...props }) {
  return <p className={cn('text-[12.5px] text-fg-subtle', className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn('p-4', className)} {...props} />;
}

export const inputClass =
  'h-8 w-full rounded-[6px] border border-border bg-surface px-2.5 text-[13px] text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none focus-visible:outline-none disabled:opacity-50';

export function Input({ className, ...props }) {
  return <input className={cn(inputClass, className)} {...props} />;
}

export function Skeleton({ className, ...props }) {
  return <div className={cn('animate-pulse rounded-[6px] bg-surface-3', className)} {...props} />;
}

export function Separator({ className, ...props }) {
  return <div className={cn('h-px w-full bg-border', className)} {...props} />;
}

// Severity as a dot plus a label. Colour is never the only signal.
const STATUS_TONE = {
  HEALTHY: 'bg-healthy',
  DEGRADED: 'bg-degraded',
  STALE: 'bg-stale',
  OFFLINE: 'bg-critical',
  MISCONFIGURED: 'bg-critical',
  DISABLED: 'bg-fg-subtle'
};

export function StatusDot({ status, className }) {
  return <span className={cn('size-1.5 rounded-full shrink-0', STATUS_TONE[status] ?? 'bg-fg-subtle', className)} />;
}

export function StatusLabel({ status, className }) {
  const tone = {
    HEALTHY: 'text-healthy', DEGRADED: 'text-degraded', STALE: 'text-stale',
    OFFLINE: 'text-critical', MISCONFIGURED: 'text-critical', DISABLED: 'text-fg-subtle'
  }[status] ?? 'text-fg-muted';
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-[13px]', tone, className)}>
      <StatusDot status={status} />
      {status.charAt(0) + status.slice(1).toLowerCase().replace(/_/g, ' ')}
    </span>
  );
}

// Thin progress bar used for freshness-versus-SLA.
export function FreshnessBar({ ratio, status }) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  const colour = { HEALTHY: 'bg-healthy', DEGRADED: 'bg-degraded', STALE: 'bg-stale', OFFLINE: 'bg-critical' }[status] ?? 'bg-fg-subtle';
  return (
    <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-3" role="img" aria-label={`Freshness ${Math.round(pct)} percent of SLA`}>
      <div className={cn('h-full rounded-full', colour)} style={{ width: `${pct}%` }} />
    </div>
  );
}