import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, ShieldCheck, X } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import {
  Panel, Badge, Button, Metric, DataTable, EmptyState, PermissionDenied,
  TextArea, stagger, fade, Note
} from '@/components/blocks.jsx';
import { KeyValue, Sheet, SheetContent, SheetHeader, SheetBody, SheetTitle, SheetDescription, SheetFooter, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/overlays';
import { useApp } from '@/lib/store.jsx';
import { ACTIONS } from '@/data/scenario.js';
import { ACTION_STATUSES, ACTION_TRANSITIONS } from '@/data/graph.js';
import { clock } from '@/lib/format.js';

const PRIORITY_TONE = { P1: 'critical', P2: 'degraded', P3: 'neutral' };

export default function Response() {
  const { audit, can, dispatch, role, actionStatus } = useApp();
  const navigate = useNavigate();
  const [filters, setFilters] = useState({ priority: 'ALL', status: 'ALL' });
  const [selected, setSelected] = useState(null);
  const [reason, setReason] = useState('');

  const rows = useMemo(() => ACTIONS
    .map(action => ({ ...action, effectiveStatus: actionStatus[action.action_id] ?? action.status }))
    .filter(action => (filters.priority === 'ALL' || action.priority === filters.priority)
      && (filters.status === 'ALL' || action.effectiveStatus === filters.status)),
    [actionStatus, filters]);

  const action = selected ? ACTIONS.find(item => item.action_id === selected) : null;
  const actionAudit = selected ? audit.filter(entry => entry.object_id === selected) : [];
  const allowed = action ? ACTION_TRANSITIONS[actionStatus[selected] ?? action.status] ?? [] : [];

  function transition(to) {
    dispatch({
      type: 'changeActionStatus', actionId: selected, to,
      entry: {
        id: `AU-${9400 + audit.length}`, at: '2026-10-12T14:09:00+05:30', actor: `${role.id.toLowerCase()}.operator`, actor_role: role.id,
        object_type: 'Action', object_id: selected, action: `STATUS_${to}`,
        summary: `Action moved to ${to}.`, reason: reason.trim() || null, request_id: `req-${8000 + audit.length}`
      }
    });
    setReason('');
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title="Response and action center"
        description="Proposed actions are recommendations for human review. Nothing here is dispatched or executed."
        actions={<Button variant="primary" size="md" onClick={() => navigate('/incidents/INC-104/cascade')}><Plus />New action from recommendation</Button>}
      />

      <PageBody className="space-y-4">
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-app border border-border bg-border lg:grid-cols-4">
            {[
              { label: 'Proposed', value: rows.filter(item => item.effectiveStatus === 'PROPOSED').length },
              { label: 'Needs review', value: rows.filter(item => item.effectiveStatus === 'NEEDS_REVIEW').length, tone: 'degraded' },
              { label: 'In progress', value: rows.filter(item => ['APPROVED', 'ASSIGNED', 'IN_PROGRESS'].includes(item.effectiveStatus)).length },
              { label: 'High impact', value: rows.filter(item => item.high_impact).length }
            ].map(item => (
              <div key={item.label} className="bg-surface px-4 py-3">
                <Metric label={item.label} value={item.value} tone={item.tone} />
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="w-[160px]">
              <label className="sr-only" htmlFor="priority-filter">Priority filter</label>
              <Select value={filters.priority} onValueChange={value => setFilters(prev => ({ ...prev, priority: value }))}>
                <SelectTrigger id="priority-filter"><SelectValue placeholder="Any priority" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any priority</SelectItem>
                  {['P1', 'P2', 'P3'].map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[200px]">
              <label className="sr-only" htmlFor="status-filter">Status filter</label>
              <Select value={filters.status} onValueChange={value => setFilters(prev => ({ ...prev, status: value }))}>
                <SelectTrigger id="status-filter"><SelectValue placeholder="Any status" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any status</SelectItem>
                  {ACTION_STATUSES.map(option => <SelectItem key={option} value={option}>{option.replace(/_/g, ' ').toLowerCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <span className="ml-auto text-[12.5px] text-fg-subtle tabular-nums">{rows.length} of {ACTIONS.length} actions</span>
          </div>

          <Panel bodyClassName="p-0">
            <DataTable
              rowId={row => row.action_id}
              onRowClick={row => setSelected(row.action_id)}
              selectedId={selected}
              empty={<EmptyState title="No actions match" body="No action matches this filter combination. Clear a filter to widen the set." />}
              columns={[
                { key: 'priority', label: 'Priority', render: row => <Badge tone={PRIORITY_TONE[row.priority]}>{row.priority}</Badge> },
                { key: 'incident', label: 'Incident', render: row => <span className="text-[12.5px] font-medium text-accent tabular-nums">{row.incident_id}</span> },
                { key: 'type', label: 'Recommended action', render: row => (
                  <span><span className="block text-[13px] font-medium text-fg">{row.type}</span>
                    <span className="block text-[12px] leading-snug text-fg-muted">{row.rationale}</span></span>
                ) },
                { key: 'evidence', label: 'Why', render: row => <span className="font-mono text-[12px] text-fg-subtle">{row.evidence_refs.join(', ')}</span> },
                { key: 'owner', label: 'Owner', render: row => row.owner ?? <span className="text-fg-subtle">Unassigned</span> },
                { key: 'effectiveStatus', label: 'Status', render: row => <Badge tone="neutral">{row.effectiveStatus.replace(/_/g, ' ').toLowerCase()}</Badge> },
                { key: 'updated_at', label: 'Updated', align: 'right', render: row => <span className="text-[12.5px] text-fg-subtle tabular-nums">{clock(row.updated_at)}</span> }
              ]}
              rows={rows}
            />
          </Panel>

          <Note>
            Actions configured as high impact require supervisor approval before they can proceed. The permission check is
            applied to the API, not only to this control.
          </Note>
        </motion.div>
      </PageBody>

      <AnimatePresence>
        {action && (
          <Sheet open onOpenChange={open => !open && setSelected(null)}>
            <SheetContent>
              <SheetHeader>
                <div className="pr-8">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[12px] font-medium text-accent tabular-nums">{action.action_id}</span>
                    <Badge tone={PRIORITY_TONE[action.priority]}>{action.priority}</Badge>
                    <Badge tone="neutral">{actionStatus[selected] ?? action.status}</Badge>
                    {action.high_impact && <Badge tone="accent"><ShieldCheck />approval</Badge>}
                  </div>
                  <SheetTitle className="mt-1.5">{action.type}</SheetTitle>
                  <SheetDescription>Incident {action.incident_id} · created {clock(action.created_at)} IST</SheetDescription>
                </div>
              </SheetHeader>

              <SheetBody className="space-y-6">
                <section>
                  <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Assessment</h3>
                  <div className="grid grid-cols-2 gap-3">
                    <Metric label="Expected benefit" value={action.expected_benefit} tone="healthy" />
                    <Metric label="Uncertainty" value={action.uncertainty.split('.')[0]} tone="degraded" />
                  </div>
                  <p className="mt-3 text-[13px] leading-snug text-fg-muted">{action.rationale}</p>
                </section>

                <section>
                  <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Originating evidence</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {action.evidence_refs.map(id => (
                      <Button key={id} size="sm" variant="ghost"
                        onClick={() => navigate(`/incidents/${action.incident_id}/evidence`)}>{id}</Button>
                    ))}
                  </div>
                </section>

                <section>
                  <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Configuration</h3>
                  <dl>
                    <KeyValue label="Owner">{action.owner ?? 'Unassigned'}</KeyValue>
                    <KeyValue label="Due window" mono>{action.due_at ? `${clock(action.due_at)} IST` : 'Not set'}</KeyValue>
                    <KeyValue label="Dependencies">
                      {action.dependencies.length ? action.dependencies.join(', ') : <span className="text-fg-subtle">none</span>}
                    </KeyValue>
                    <KeyValue label="High impact">
                      <span className={action.high_impact ? 'text-accent' : 'text-fg-muted'}>
                        {action.high_impact ? 'approval required' : 'no'}
                      </span>
                    </KeyValue>
                  </dl>
                </section>

                <section>
                  <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Risks of this action</h3>
                  {action.risks.length
                    ? <ul className="ml-4 list-disc space-y-1 text-[12.5px] leading-snug text-fg-muted">{action.risks.map(item => <li key={item}>{item}</li>)}</ul>
                    : <p className="text-[12.5px] text-fg-subtle">None recorded.</p>}
                </section>

                <section>
                  <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Audit history</h3>
                  {actionAudit.length === 0
                    ? <p className="text-[12.5px] text-fg-subtle">No transitions recorded yet.</p>
                    : (
                      <div className="space-y-1.5">
                        {actionAudit.map(entry => (
                          <div key={entry.id} className="border-b border-border pb-1.5 text-[12.5px] last:border-0">
                            <span className="text-fg-subtle tabular-nums">{clock(entry.at)}</span>{' '}
                            <span className="text-fg">{entry.action.replace(/_/g, ' ').toLowerCase()}</span>{' '}
                            <span className="text-fg-subtle">by {entry.actor}</span>
                            {entry.reason && <p className="mt-0.5 text-fg-muted">reason: {entry.reason}</p>}
                          </div>
                        ))}
                      </div>
                    )}
                </section>

                <section>
                  <h3 className="mb-2 text-[12.5px] font-medium text-fg-muted">Transition this action</h3>
                  {!can('approve') ? <PermissionDenied missing="action approval" /> : (
                    <div className="space-y-3">
                      <TextArea label="Reason (recorded in the audit trail)" value={reason} onChange={setReason} rows={2}
                        placeholder="Why is this transition appropriate? Rejection and cancellation require a reason." />
                      <div className="flex flex-wrap gap-2">
                        {allowed.length === 0 && <span className="text-[12.5px] text-fg-subtle">No further transitions are permitted from this status.</span>}
                        {allowed.map(next => (
                          <Button key={next} size="sm"
                            variant={['APPROVED', 'COMPLETED'].includes(next) ? 'primary' : 'default'}
                            disabled={['REJECTED', 'CANCELLED'].includes(next) && !reason.trim()}
                            title={['REJECTED', 'CANCELLED'].includes(next) && !reason.trim() ? 'A reason is required' : undefined}
                            onClick={() => transition(next)}>
                            {next.replace(/_/g, ' ').toLowerCase()}
                          </Button>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              </SheetBody>
            </SheetContent>
          </Sheet>
        )}
      </AnimatePresence>
    </div>
  );
}