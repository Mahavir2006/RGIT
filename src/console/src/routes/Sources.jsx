import { useMemo, useState } from 'react';
import {
  Database, RefreshCw, Search, MoreHorizontal, Plug, Clock, KeyRound,
  Activity, ExternalLink, AlertTriangle, ChevronDown, X, Info
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { Button, Badge, Card, Input, StatusLabel, FreshnessBar, Skeleton } from '@/components/ui';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Sheet, SheetContent,
  SheetHeader, SheetBody, SheetTitle, SheetDescription, SheetFooter, KeyValue,
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger
} from '@/components/overlays';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { useApp } from '@/lib/store.jsx';
import { clock, relativeLag, ago } from '@/lib/format.js';
import { cn } from '@/lib/utils';

const MODE_TONE = { LIVE_API: 'accent', HISTORICAL: 'neutral', REPLAY: 'neutral', SYNTHETIC: 'neutral', MANUAL: 'neutral' };
const ACCESS_ICON = { live_keyless: Plug, keyed: KeyRound, portal: ExternalLink, internal: Activity };
const ACCESS_TEXT = { live_keyless: 'No credential', keyed: 'API key', portal: 'Web portal', internal: 'Generated' };

const STATES = ['HEALTHY', 'DEGRADED', 'STALE', 'OFFLINE', 'MISCONFIGURED', 'DISABLED'];

// Seconds since the last successful read, used for the freshness bar.
function freshnessRatio(source) {
  if (!source.lastSuccess) return 0;
  const last = new Date(`2026-10-12T${source.lastSuccess}:00+05:30`).getTime();
  const now = new Date('2026-10-12T14:05:00+05:30').getTime();
  const elapsedMinutes = Math.max(0, (now - last) / 60000);
  return Math.min(1.5, elapsedMinutes / Math.max(1, source.freshnessSlaMinutes));
}

// Segmented health summary. Clicking a segment filters the table.
function HealthSummary({ sources, value, onChange }) {
  const segments = [
    { key: 'HEALTHY', label: 'Healthy', count: sources.filter(item => item.health === 'HEALTHY').length, dot: 'bg-healthy' },
    { key: 'DEGRADED', label: 'Degraded', count: sources.filter(item => item.health === 'DEGRADED').length, dot: 'bg-degraded' },
    { key: 'OFFLINE', label: 'Stale or offline', count: sources.filter(item => ['STALE', 'OFFLINE'].includes(item.health)).length, dot: 'bg-critical' },
    { key: 'REPLAY', label: 'Replay or synthetic', count: sources.filter(item => ['REPLAY', 'SYNTHETIC', 'MANUAL'].includes(item.mode)).length, dot: 'bg-fg-subtle' }
  ];
  const total = sources.length || 1;

  return (
    <div>
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
        {segments.map(segment => (
          segment.count > 0 && (
            <button
              key={segment.key}
              onClick={() => onChange(value === segment.key ? 'ALL' : segment.key)}
              title={`${segment.label}: ${segment.count}`}
              aria-label={`Filter by ${segment.label}, ${segment.count} connectors`}
              className={cn('h-full transition-opacity hover:opacity-80', segment.dot, value === segment.key && 'ring-2 ring-inset ring-fg/20')}
              style={{ width: `${(segment.count / total) * 100}%` }}
            />
          )
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1.5">
        {segments.map(segment => (
          <button
            key={segment.key}
            onClick={() => onChange(value === segment.key ? 'ALL' : segment.key)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-[5px] px-1 py-0.5 text-[12.5px] transition-colors hover:text-fg',
              value === segment.key ? 'text-fg font-medium' : 'text-fg-muted'
            )}
          >
            <span className={cn('size-1.5 rounded-full', segment.dot)} />
            {segment.label}
            <span className="tabular-nums text-fg-subtle">{segment.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Sources() {
  const { sources, dispatch, can, simulatedOutage } = useApp();
  const [query, setQuery] = useState('');
  const [health, setHealth] = useState('ALL');
  const [category, setCategory] = useState('ALL');
  const [selected, setSelected] = useState(null);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState(null);

  const categories = useMemo(() => [...new Set(sources.map(item => item.category))].sort(), [sources]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return sources.filter(source => {
      if (health !== 'ALL' && source.health !== health) return false;
      if (category !== 'ALL' && source.category !== category) return false;
      if (!needle) return true;
      return `${source.name} ${source.category} ${source.connector} ${source.dataClass}`.toLowerCase().includes(needle);
    });
  }, [sources, query, health, category]);

  const source = selected ? sources.find(item => item.source_id === selected) : null;
  const activeFilters = [health !== 'ALL', category !== 'ALL', query.trim() !== ''].filter(Boolean).length;

  function clearFilters() { setHealth('ALL'); setCategory('ALL'); setQuery(''); }

  function checkNow(target) {
    setChecking(true);
    setCheckResult(null);
    setTimeout(() => {
      setChecking(false);
      setCheckResult(
        target.credential === 'INVALID'
          ? { ok: false, text: 'CREDENTIAL_INVALID — the connector secret reference failed validation. No events were produced by this run.' }
          : target.health === 'OFFLINE'
            ? { ok: false, text: 'NO_AUTHORIZED_FEED — no reachable upstream in this dataset. Unrelated connectors are unaffected.' }
            : target.health === 'DEGRADED'
              ? { ok: false, text: 'RATE_LIMITED_429 — the provider throttled this run. Unrelated connectors continued normally.' }
              : { ok: true, text: `Read ${target.eventCount} records. Watermark advanced to ${target.eventWatermark ?? 'n/a'}.` }
      );
    }, 700);
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title="Data sources"
        description="Feed freshness, connector health and provenance mode for every source in the operating area."
        actions={<>
          <Button variant="primary" size="md" onClick={() => setSelected(sources[0]?.source_id)} disabled={!can('ingest')}>
            <RefreshCw className={cn(checking && 'animate-spin')} />Check all
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="default" size="md"><MoreHorizontal />Actions<ChevronDown className="size-3.5" /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={() => sources.forEach(item => { if (!simulatedOutage.includes(item.source_id)) dispatch({ type: 'toggleOutage', sourceId: item.source_id }); })}>
                <AlertTriangle />Simulate an outage
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={clearFilters}>Reset filters</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem>Export connector report</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>}
      />

      <PageBody className="space-y-4">
        {simulatedOutage.length > 0 && (
          <div className="flex items-center gap-2 rounded-[8px] border border-critical/25 bg-critical-soft px-3 py-2 text-[12.5px] text-critical">
            <AlertTriangle className="size-3.5 shrink-0" />
            <span>{simulatedOutage.length} connector{simulatedOutage.length > 1 ? 's' : ''} forced offline for this walkthrough. Failures stay isolated.</span>
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => simulatedOutage.forEach(id => dispatch({ type: 'toggleOutage', sourceId: id }))}>
              Restore all
            </Button>
          </div>
        )}

        <Card className="px-4 py-3.5">
          <HealthSummary sources={sources} value={health} onChange={setHealth} />
        </Card>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-[260px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle" />
            <Input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search connectors" aria-label="Search connectors" className="pl-8" />
          </div>

          <Select value={health} onValueChange={setHealth}>
            <SelectTrigger className="w-[168px]" aria-label="Filter by health"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">Any health</SelectItem>
              {STATES.map(item => <SelectItem key={item} value={item}>{item.charAt(0) + item.slice(1).toLowerCase()}</SelectItem>)}
            </SelectContent>
          </Select>

          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-[168px]" aria-label="Filter by category"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">Any category</SelectItem>
              {categories.map(item => <SelectItem key={item} value={item}>{item}</SelectItem>)}
            </SelectContent>
          </Select>

          {activeFilters > 0 && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X />Clear {activeFilters} filter{activeFilters > 1 ? 's' : ''}
            </Button>
          )}

          <span className="ml-auto text-[12.5px] text-fg-subtle tabular-nums">
            {rows.length} of {sources.length} connectors
          </span>
        </div>

        <Card className="overflow-hidden">
          {checking && rows.length === 0 ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-11 w-full" />)}
            </div>
          ) : rows.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
              <Database className="size-5 text-fg-subtle" />
              <div className="text-[13px] font-medium text-fg">No connectors match</div>
              <p className="max-w-[46ch] text-[12.5px] text-fg-muted">
                Nothing matches the current search, health and category filters. Clear a filter to widen the set.
              </p>
              <Button variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse">
                <thead className="sticky top-0 z-10 bg-surface-2">
                  <tr className="border-b border-border">
                    {['Source', 'Status', 'Mode', 'Access', 'Last sync', 'Freshness', 'Error'].map(heading => (
                      <th key={heading} className="px-4 py-2 text-left text-[12px] font-medium text-fg-subtle">{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(item => {
                    const AccessIcon = ACCESS_ICON[item.access];
                    const isSimulated = simulatedOutage.includes(item.source_id);
                    return (
                      <tr
                        key={item.source_id}
                        tabIndex={0}
                        onClick={() => setSelected(item.source_id)}
                        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(item.source_id); } }}
                        className={cn(
                          'h-14 cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-surface-2',
                          selected === item.source_id && 'bg-accent-soft'
                        )}
                      >
                        <td className="px-4">
                          <div className="text-[13px] font-medium text-fg">{item.name}</div>
                          <div className="mt-0.5 text-[12px] text-fg-subtle">{item.category} · {item.connector}</div>
                        </td>
                        <td className="px-4"><StatusLabel status={item.health} /></td>
                        <td className="px-4">
                          <Badge tone={MODE_TONE[item.mode]}>{item.mode.replace('_', ' ').toLowerCase()}</Badge>
                        </td>
                        <td className="px-4">
                          <span className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted">
                            <AccessIcon className="size-3.5 text-fg-subtle" />
                            {ACCESS_TEXT[item.access]}
                          </span>
                        </td>
                        <td className="px-4">
                          <time className="block text-[13px] text-fg tabular-nums" dateTime={item.lastSuccess ?? undefined} title={item.lastSuccess ? `${item.lastSuccess} IST` : 'Never'}>
                            {item.lastSuccess ? ago(item.lastSuccess) : 'never'}
                          </time>
                          <span className="mt-0.5 block text-[12px] text-fg-subtle tabular-nums">
                            {item.lastSuccess ? `${item.lastSuccess} IST` : 'no successful read'}
                          </span>
                        </td>
                        <td className="px-4">
                          <div className="flex items-center gap-2">
                            <FreshnessBar ratio={freshnessRatio(item)} status={item.health} />
                            <span className="text-[12px] text-fg-subtle tabular-nums">{relativeLag(item.eventLagSeconds)}</span>
                          </div>
                        </td>
                        <td className="px-4">
                          {item.errorClass ? (
                            <span className="text-[12.5px] text-critical">{item.errorClass.replace(/_/g, ' ').toLowerCase()}</span>
                          ) : isSimulated ? (
                            <span className="text-[12.5px] text-degraded">simulated outage</span>
                          ) : (
                            <span className="text-[12.5px] text-fg-subtle">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="flex items-start gap-2 rounded-[8px] border border-border bg-surface-2 px-3 py-2.5 text-[12.5px] text-fg-muted">
          <Info className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
          <p>
            A connector can be perfectly healthy while replaying. Operating mode is tracked separately from health, and a silent
            source is reported as an observability gap rather than as evidence that conditions are safe.
          </p>
        </div>
      </PageBody>

      <AnimatePresence>
        {source && (
          <Sheet open onOpenChange={open => !open && setSelected(null)}>
            <SheetContent>
              <SheetHeader>
                <div className="pr-8">
                  <SheetTitle>{source.name}</SheetTitle>
                  <SheetDescription>{source.category} · {source.connector} · {source.endpointClass}</SheetDescription>
                </div>
              </SheetHeader>

              <SheetBody>
                <div className="space-y-6">
                  <section>
                    <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Overview</h3>
                    <dl>
                      <KeyValue label="Status"><StatusLabel status={source.health} /></KeyValue>
                      <KeyValue label="Operating mode">
                        <Badge tone={MODE_TONE[source.mode]}>{source.mode.replace('_', ' ').toLowerCase()}</Badge>
                      </KeyValue>
                      <KeyValue label="Data class">{source.dataClass}</KeyValue>
                      <KeyValue label="Units" mono>{source.units}</KeyValue>
                      <KeyValue label="Events in window" mono>{source.eventCount}</KeyValue>
                    </dl>
                  </section>

                  <section>
                    <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Configuration</h3>
                    <dl>
                      <KeyValue label="Owner" mono>platform.data</KeyValue>
                      <KeyValue label="Access">{ACCESS_TEXT[source.access]}</KeyValue>
                      {/* Only the credential state is ever shown, never the value. */}
                      <KeyValue label="Credential">
                        {source.credential === 'NOT_REQUIRED'
                          ? <span className="text-healthy">not required</span>
                          : <span className={source.credential === 'MISSING' ? 'text-degraded' : 'text-critical'}>{source.credential.toLowerCase()}</span>}
                      </KeyValue>
                      <KeyValue label="Polling cadence">{source.cadence}</KeyValue>
                      <KeyValue label="Freshness SLA">
                        {source.freshnessSlaMinutes >= 1440
                          ? `${Math.round(source.freshnessSlaMinutes / 1440)} days`
                          : `${source.freshnessSlaMinutes} min`}
                      </KeyValue>
                      <KeyValue label="Reference">
                        {source.reference
                          ? <a href={source.reference} target="_blank" rel="noreferrer" className="text-accent hover:underline">{source.reference.replace(/^https?:\/\//, '')}</a>
                          : '—'}
                      </KeyValue>
                    </dl>
                  </section>

                  <section>
                    <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Recent activity</h3>
                    <dl>
                      <KeyValue label="Last attempt" mono>{source.lastAttempt ? `${source.lastAttempt} IST` : 'never'}</KeyValue>
                      <KeyValue label="Last success" mono>{source.lastSuccess ? `${source.lastSuccess} IST` : 'never'}</KeyValue>
                      <KeyValue label="Event watermark" mono>{source.eventWatermark ?? '—'}</KeyValue>
                      <KeyValue label="Ingest lag" mono>{relativeLag(source.eventLagSeconds)}</KeyValue>
                      {source.errorClass && <KeyValue label="Last error"><span className="text-critical">{source.errorClass.replace(/_/g, ' ').toLowerCase()}</span></KeyValue>}
                    </dl>

                    <div className="mt-3 rounded-[6px] border border-border bg-surface-2 px-3 py-2.5">
                      <div className="mb-1 text-[12px] font-medium text-fg">Remediation</div>
                      <p className="text-[12.5px] leading-snug text-fg-muted">{source.notes}</p>
                    </div>
                  </section>

                  {checkResult && (
                    <div className={cn(
                      'rounded-[6px] border px-3 py-2.5 text-[12.5px]',
                      checkResult.ok ? 'border-healthy/25 bg-healthy-soft text-healthy' : 'border-critical/25 bg-critical-soft text-critical'
                    )}>
                      <div className="font-medium">{checkResult.ok ? 'Check succeeded' : 'Check failed'}</div>
                      <p className="mt-0.5 text-fg-muted">{checkResult.text}</p>
                    </div>
                  )}
                </div>
              </SheetBody>

              <SheetFooter>
                <Button variant="primary" size="md" onClick={() => checkNow(source)} disabled={!can('ingest') || checking}>
                  <RefreshCw className={cn(checking && 'animate-spin')} />{checking ? 'Checking' : 'Check now'}
                </Button>
                <Button variant="default" size="md" onClick={() => dispatch({ type: 'toggleOutage', sourceId: source.source_id })}>
                  {simulatedOutage.includes(source.source_id) ? 'Restore source' : 'Simulate outage'}
                </Button>
                {!can('ingest') && <span className="ml-auto text-[12px] text-fg-subtle">Read-only for your role</span>}
              </SheetFooter>
            </SheetContent>
          </Sheet>
        )}
      </AnimatePresence>
    </div>
  );
}