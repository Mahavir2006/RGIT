import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, RefreshCw, Download, ShieldCheck, TriangleAlert } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { Panel, Badge, Button, Metric, DataTable, EmptyState, stagger, fade, Note } from '@/components/blocks.jsx';
import { StatusLabel } from '@/components/ui';
import { useApp } from '@/lib/store.jsx';
import { evidenceFor } from '@/data/graph.js';
import { SCENARIO, CASCADE_SCENARIOS, ACTIONS, CANDIDATES } from '@/data/scenario.js';
import { ago, pct } from '@/lib/format.js';
import SentinelMap from '@/components/SentinelMap.jsx';
import { cn } from '@/lib/utils';

function severityTone(severity) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'critical';
  if (severity === 'MODERATE') return 'degraded';
  return 'neutral';
}

export default function Overview() {
  const { store, incidents, sources, health, area, audit } = useApp();
  const navigate = useNavigate();

  const scoped = useMemo(
    () => (area === 'All areas' ? incidents : incidents.filter(item => item.area_name === area)),
    [incidents, area]
  );

  const top = useMemo(() => {
    const weight = { CRITICAL: 5, HIGH: 4, MODERATE: 3, LOW: 2, INFO: 1 };
    return [...scoped].sort((a, b) => weight[b.severity] - weight[a.severity] || a.updated_at.localeCompare(b.updated_at)).slice(0, 4);
  }, [scoped]);

  const trend = useMemo(() => [2, 2, 2, 3, 3, 3, 4, 4, 3, 3, 4, 4, 5, 5, 4, 4, 5, 4, 4, 3, 3, 3, 2, 2], []);
  const pending = ACTIONS.find(action => action.status === 'NEEDS_REVIEW');
  const recentAudit = audit.slice(0, 5);

  return (
    <div className="min-h-full">
      <PageHeader
        title="Overview"
        description="What needs attention right now."
        actions={<>
          <Button size="md"><RefreshCw />Refresh</Button>
          <Button variant="primary" size="md"><Download />Export</Button>
        </>}
      />

      <PageBody className="space-y-4">
        {/* One compact strip rather than four oversized cards. */}
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-app border border-border bg-border lg:grid-cols-4">
          {[
            { label: 'Active incidents', value: scoped.length, to: '/incidents' },
            { label: 'Critical and high', value: scoped.filter(i => ['CRITICAL', 'HIGH'].includes(i.severity)).length, tone: 'critical' },
            { label: 'Feeds degraded', value: sources.filter(s => s.health !== 'HEALTHY').length, tone: 'degraded', to: '/sources' },
            { label: 'High cascade risk', value: CASCADE_SCENARIOS.filter(c => c.baseline_risk === 'HIGH').length, to: '/incidents/INC-104/cascade' }
          ].map(item => (
            <button key={item.label} onClick={() => item.to && navigate(item.to)}
              className="bg-surface px-4 py-3 text-left transition-colors hover:bg-surface-2">
              <div className="text-[12px] text-fg-subtle">{item.label}</div>
              <div className={cn('mt-1 text-[24px] font-semibold leading-none tabular-nums',
                item.tone === 'critical' ? 'text-critical' : item.tone === 'degraded' ? 'text-degraded' : 'text-fg')}>
                {item.value}
              </div>
            </button>
          ))}
        </div>

        {/* Map leads; the priority queue sits beside it and stays short. */}
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <Panel bodyClassName="p-0" className="overflow-hidden">
            <div className="flex items-center gap-3 border-b border-border px-4 py-3">
              <h2 className="text-[14px] font-semibold text-fg">Active incidents</h2>
              <span className="text-[12.5px] text-fg-subtle tabular-nums">{scoped.length}</span>
              <Button variant="ghost" size="sm" className="ml-auto" onClick={() => navigate('/operations')}>
                Open map<ArrowRight />
              </Button>
            </div>
            <div className="relative h-[420px]">
              <SentinelMap
                incidents={scoped}
                candidates={CANDIDATES}
                layers={{ incidents: true, candidates: true, assets: true, impactZones: true, dependencies: false, rainfall: true }}
                replay={100}
                height={420}
                showLegend={false}
              />
            </div>
          </Panel>

          <div className="flex flex-col gap-4">
            <Panel title="Priority queue" description="Ranked by severity, then last update">
              {scoped.length === 0 ? (
                <EmptyState title="No incidents in this area"
                  body="Widen the area or the time window before concluding the area is quiet." />
              ) : (
                <div className="divide-y divide-border">
                  {top.map(incident => (
                    <IncidentRow key={incident.incident_id} store={store} incident={incident}
                      onOpen={() => navigate(`/incidents/${incident.incident_id}`)} />
                  ))}
                  {scoped.length > top.length && (
                    <button onClick={() => navigate('/incidents')}
                      className="flex w-full items-center gap-1.5 px-4 py-2.5 text-[12.5px] text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg">
                      {scoped.length - top.length} more<ArrowRight className="size-3.5" />
                    </button>
                  )}
                </div>
              )}
            </Panel>

            <Panel title="Severity trend" description="Active incidents over the window">
              <div className="flex h-[72px] items-end gap-[3px]">
                {trend.map((value, index) => (
                  <motion.span key={index} title={`${value} active`}
                    initial={{ height: 0 }} animate={{ height: `${(value / 6) * 100}%` }}
                    transition={{ delay: index * 0.014, duration: 0.3 }}
                    className={cn('flex-1 rounded-[2px]', value >= 4 ? 'bg-critical/70' : value >= 3 ? 'bg-degraded/70' : 'bg-accent/50')}
                  />
                ))}
              </div>
              <div className="mt-2 flex justify-between text-[12px] text-fg-subtle"><span>−2h</span><span>−1h</span><span>now</span></div>
            </Panel>
          </div>
        </div>

        {/* Secondary row: three equal panels, deliberately low on words. */}
        <div className="grid gap-4 lg:grid-cols-3">
          <Panel title="Source freshness" bodyClassName="p-0">
            <DataTable
              rowId={row => row.source_id}
              onRowClick={() => navigate('/sources')}
              maxHeight={236}
              columns={[
                { key: 'name', label: 'Source', render: row => <span className="text-[13px]">{row.name}</span> },
                { key: 'health', label: 'Status', render: row => <StatusLabel status={row.health} /> }
              ]}
              rows={sources.slice(0, 6)}
            />
          </Panel>

          <Panel title="Cascade risk" description="Configured scenarios">
            <div className="space-y-3">
              {CASCADE_SCENARIOS.map(scenario => (
                <button key={scenario.id} onClick={() => navigate('/incidents/INC-104/cascade')}
                  className="block w-full text-left">
                  <div className="flex items-center gap-2">
                    <span className={cn('size-1.5 shrink-0 rounded-full', {
                      CRITICAL: 'bg-critical', HIGH: 'bg-degraded', MODERATE: 'bg-stale', LOW: 'bg-info'
                    }[scenario.baseline_risk])} />
                    <span className="text-[13px] text-fg">{scenario.name}</span>
                    <span className="ml-auto text-[12px] text-fg-subtle tabular-nums">{pct(scenario.confidence)}</span>
                  </div>
                  <div className="mt-1 truncate text-[12px] text-fg-subtle">
                    {scenario.nodes.slice(0, 3).map(node => node.label).join(' → ')} →
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Recent changes">
            <div className="space-y-2.5">
              {recentAudit.map(entry => (
                <div key={entry.id} className="flex gap-2 text-[12.5px]">
                  <span className="shrink-0 text-fg-subtle tabular-nums">{ago(entry.at)}</span>
                  <span className="text-fg-muted">
                    <span className="text-fg">{entry.actor.split('.')[0]}</span>{' '}
                    {entry.action.replace(/_/g, ' ').toLowerCase()}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {pending && (
          <Note tone="warning" icon={ShieldCheck}>
            <span className="flex flex-wrap items-center gap-2">
              <span><strong className="text-fg">{pending.action_id}</strong> · {pending.type} · {pending.priority}</span>
              <Badge tone="degraded">supervisor approval required</Badge>
              <Button size="sm" variant="primary" onClick={() => navigate('/response')}>Review<ArrowRight /></Button>
            </span>
          </Note>
        )}

        {(health.offline.length > 0 || health.stale.length > 0) && (
          <Note tone="warning" icon={TriangleAlert}>
            {health.offline.length} offline and {health.stale.length} stale connectors. Unaffected panels keep serving data;
            a missing signal is not evidence that conditions are safe.
          </Note>
        )}
      </PageBody>
    </div>
  );
}

// Compact two-line row: title plus a single confidence figure. The detail lives on the
// incident page, so the overview stays scannable.
function IncidentRow({ store, incident, onOpen }) {
  const evidence = evidenceFor(store, incident.incident_id);
  const supporting = evidence.filter(edge => edge._type === 'SUPPORTS').length;
  const contradicting = evidence.filter(edge => edge._type === 'CONTRADICTS').length;

  return (
    <button onClick={onOpen} className="block w-full px-4 py-2.5 text-left transition-colors hover:bg-surface-2">
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-medium text-accent tabular-nums">{incident.incident_id}</span>
        <Badge tone={severityTone(incident.severity)}>{incident.severity.toLowerCase()}</Badge>
        <span className="ml-auto text-[12px] text-fg-subtle tabular-nums">{ago(incident.updated_at)}</span>
      </div>
      <div className="mt-0.5 truncate text-[13px] text-fg">{incident.title}</div>
      <div className="mt-0.5 flex gap-3 text-[12px] text-fg-subtle tabular-nums">
        <span className="text-healthy">{supporting} support</span>
        <span className="text-critical">{contradicting} conflict</span>
        <span>cause {incident.confidence.cause.toFixed(2)}</span>
      </div>
    </button>
  );
}