// The animated indicator visual, shared by the map overlay, the legend and the incident list.
//
// One component draws all three on purpose. If the legend showed a static swatch, or the list
// showed a plain dot, the operator would have to learn the vocabulary twice and could easily
// assume the list and the map were describing different things. Here they are literally the
// same element at a different size.
import { cn } from '@/lib/utils';

export default function IndicatorVisual({
  descriptor, areaName, selected = false, className = '', scale, ...rest
}) {
  const rings = Array.from({ length: descriptor.rings });

  return (
    <span
      className={cn('us-indicator__body block', className)}
      style={{
        '--us-colour': descriptor.colour,
        '--us-ring-duration': descriptor.ringDuration,
        '--us-ring-opacity': String(descriptor.glow),
        '--us-halo-min': String(descriptor.glow * 0.55),
        '--us-halo-max': String(descriptor.glow),
        '--us-orbit-duration': descriptor.kind === 'predicted' ? '9s' : '7s',
        // Scale is passed as the custom property rather than a Tailwind scale utility:
        // `.us-indicator__body` sets transform in unlayered CSS, which outranks layered
        // utilities, so a `scale-*` class would be silently ignored.
        ...(scale !== undefined ? { '--us-zoom-scale': String(scale) } : {}),
        ...(rest.style ?? {})
      }}
      data-selected={String(selected)}
    >
      {/* Uncertainty boundary sits under everything: it is context, not the effect. */}
      {descriptor.uncertaintyM > 0 && <span className="us-uncertainty block" />}

      {descriptor.glow > 0 && <span className="us-halo block" />}

      {rings.map((_, index) => (
        <span
          key={index}
          className={cn('us-ring block', index > 0 && 'us-ring--outer')}
          style={descriptor.broken
            ? { animationName: 'us-broken', animationDuration: descriptor.ringDuration }
            : undefined}
        />
      ))}

      {/* A predicted cascade gets travelling direction arrows, so the risk reads as
          directional and projected rather than as a static ring. */}
      {descriptor.arrows && (
        <span className="us-arrows">
          {[0, 1, 2].map(index => (
            <span
              key={index}
              className="us-arbit"
              style={{ transform: `rotate(${index * 120}deg) translateY(-58px)` }}
            >
              <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
                <path d="M5 0 L10 9 L5 6.4 L0 9 Z" fill="var(--us-colour)" opacity="0.9" />
              </svg>
            </span>
          ))}
        </span>
      )}

      {descriptor.orbit && (
        <span className="us-orbit block">
          {[0, 1, 2].map(index => (
            <span
              key={index}
              className="us-orbit__dot"
              style={{ transform: `rotate(${index * 120}deg) translateY(-26px)` }}
            />
          ))}
        </span>
      )}

      <span
        className={cn(
          'us-core',
          descriptor.kind === 'predicted' && 'us-core--predicted',
          descriptor.kind === 'candidate' && 'us-core--candidate',
          descriptor.historical && 'us-core--historical'
        )}
        dangerouslySetInnerHTML={{ __html: descriptor.icon }}
      />

      {/* Captions belong to the map and the list, never to the legend swatch, which is too
          small to carry one without becoming unreadable. */}
      {descriptor.showCaption && (
        <span className="us-label">
          {descriptor.tag && <span className="us-label__tag">{descriptor.tag}</span>}
          {descriptor.severity && <span className="us-label__sev">{descriptor.severity.toLowerCase()}</span>}
          <span className="us-label__area">{areaName}</span>
        </span>
      )}
    </span>
  );
}