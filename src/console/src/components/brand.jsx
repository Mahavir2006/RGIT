import { cn } from '@/lib/utils';

// Sentinel Aperture: three concentric partial rings and a core, matching the contours
// extruded for the WebGL scenes. The optional sweep ring is the live status variant.
export function SentinelMark({ size = 22, className, animate = false }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="-3.2 -3.2 6.4 6.4"
      className={cn('shrink-0', className)}
      role="img"
      aria-label="Urban Sentinel"
    >
      <g fill="none" stroke="currentColor" strokeWidth="0.6">
        <path d="M 2.6 0 A 2.6 2.6 0 1 0 1.81 -1.81 L 1.27 -1.27 A 1.86 1.86 0 1 1 1.32 -1.32 Z" />
        <path d="M 0.65 1.23 A 1.52 1.52 0 1 0 -0.36 -1.48 L -0.81 -0.67 A 0.99 0.99 0 1 1 -0.25 -0.97 Z" opacity="0.5" />
      </g>
      <circle cx="0" cy="0" r="0.6" fill="currentColor" />
      {animate && (
        <circle cx="0" cy="0" r="0.62" fill="none" stroke="currentColor" strokeWidth="0.1" opacity="0.6">
          <animate attributeName="r" values="0.62;3.1;0.62" dur="3.6s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.5;0;0.5" dur="3.6s" repeatCount="indefinite" />
        </circle>
      )}
    </svg>
  );
}

export function Wordmark({ className }) {
  return (
    <span className={cn('font-display text-[15px] italic tracking-[-0.01em]', className)}>
      Urban Sentinel
    </span>
  );
}