import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Check, X, ShieldCheck, Lock, TriangleAlert } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { EmptyState } from '@/components/blocks.jsx';
import {
  Panel, Tabs, Badge, Button, DataTable, Metric, Field, TextArea,
  PermissionDenied, Note, stagger, fade
} from '@/components/blocks.jsx';
import { KeyValue, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/overlays';
import { useApp, ROLES, PERMISSIONS } from '@/lib/store.jsx';
import { ANOMALY_RULES, CONFIDENCE_DIMENSIONS } from '@/data/graph.js';
import { clock } from '@/lib/format.js';
import { cn } from '@/lib/utils';

const TABS = [
  { id: 'thresholds', label: 'Thresholds' },
  { id: 'users', label: 'Users and roles' },
  { id: 'connectors', label: 'Connectors' },
  { id: 'retention', label: 'Retention' },
  { id: 'audit', label: 'Audit' }
];

const THRESHOLDS = [
  { key: 'water_level_alert', label: 'Water level alert stage', unit: 'm AMSL', scope: 'Gauge family' },
  { key: 'water_rate_alert', label: 'Water level rate alert', unit: 'm/h', scope: 'Gauge family' },
  { key: 'rain_rate_alert', label: 'Precipitation rate alert', unit: 'mm/h', scope: 'Weather family' },
  { key: 'speed_ratio_alert', label: 'Traffic speed ratio floor', unit: 'ratio', scope: 'Road segment' },
  { key: 'gauge_divergence', label: 'Cross-gauge divergence tolerance', unit: 'm', scope: 'Gauge pair' },
  { key: 'heartbeat_timeout', label: 'Sensor heartbeat timeout', unit: 'min', scope: 'Every sensor' },
  { key: 'candidate_time_window', label: 'Candidate time window', unit: 'min', scope: 'Candidate matcher' },
  { key: 'candidate_distance_window', label: 'Candidate distance window', unit: 'km', scope: 'Candidate matcher' },
  { key: 'freshness_target', label: 'Source freshness target', unit: 'min', scope: 'Every live source' }
];

const DEFAULTS = Object.fromEntries(THRESHOLDS.map(item => [
  item.key,
  { water_level_alert: 9.4, water_rate_alert: 0.18, rain_rate_alert: 25, speed_ratio_alert: 0.35, gauge_divergence: 0.35, heartbeat_timeout: 20, candidate_time_window: 45, candidate_distance_window: 2.5, freshness_target: 15 }[item.key]
]));

export default function Settings() {
  const { audit, can, dispatch, role } = useApp();
  const [tab, setTab] = useState('thresholds');
  const [values, setValues] = useState(() => Object.fromEntries(THRESHOLDS.map(item => [item.key, String(item.value)])));
  const [errors, setErrors] = useState({});
  const [saved, setSaved] = useState(null);
  const [auditFilter, setAuditFilter] = useState({ actor: 'ALL', action: 'ALL' });

  const actors = useMemo(() => ['ALL', ...new Set(audit.map(entry => entry.actor))], [audit]);
  const actions = useMemo(() => ['ALL', ...new Set(audit.map(entry => entry.action))], [audit]);
  const auditRows = useMemo(() => audit.filter(entry =>
    (auditFilter.actor === 'ALL' || entry.actor === auditFilter.actor) &&
    (auditFilter.action === 'ALL' || entry.action === auditFilter.action)), [audit, auditFilter]);

  // Invalid combinations are rejected with an actionable message rather than silently saved.
  function validate() {
    const next = {};
    const water = Number(values.water_level_alert);
    const divergence = Number(values.gauge_divergence);
    const heartbeat = Number(values.heartbeat_timeout);
    const speed = Number(values.speed_ratio_alert);
    if (!Number.isFinite(water) || water <= 0) next.water_level_alert = 'Must be a positive number of metres above datum.';
    if (!Number.isFinite(divergence) || divergence <= 0) next.gauge_divergence = 'Tolerance must be greater than zero.';
    else if (divergence >= water) next.gauge_divergence = 'Tolerance cannot exceed the absolute alert stage; every pair would disagree.';
    if (!Number.isFinite(heartbeat) || heartbeat < 5) next.heartbeat_timeout = 'A timeout below 5 minutes produces false sensor failures.';
    if (!Number.isFinite(speed) || speed <= 0 || speed > 1) next.speed_ratio_alert = 'Speed ratio must be between 0 and 1.';
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function save() {
    if (!can('configure')) return;
    if (!validate()) { setSaved({ ok: false, message: 'Rejected. Fix the highlighted thresholds before saving.' }); return; }
    setSaved({ ok: true, message: 'Saved as threshold version t-2026-10-12-3, effective 2026-10-12T14:10:00+05:30. The previous version t-2026-10-12-2 is retained.' });
    dispatch({
      type: 'appendAudit',
      entry: {
        id: `AU-${9500 + audit.length}`, at: '2026-10-12T14:10:00+05:30', actor: 'admin.sentinel', actor_role: 'ADMIN',
        object_type: 'ThresholdSet', object_id: 'thresholds', action: 'THRESHOLDS_SAVED',
        summary: 'Threshold set validated and versioned as t-2026-10-12-3.', reason: 'Operator configuration change.', request_id: 'req-8102'
      }
    });
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title="Settings and audit"
        description="Who can change what, which thresholds apply, and what changed."
        actions={can('configure')
          ? <Button variant="primary" size="md" onClick={save}><Check />Validate and save</Button>
          : <Badge tone="neutral"><Lock />Read-only for your role</Badge>}
      />

      <PageBody className="space-y-4">
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          {saved && (
            <Note tone={saved.ok ? 'neutral' : 'critical'} icon={saved.ok ? Check : TriangleAlert}>{saved.message}</Note>
          )}

          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === 'thresholds' && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              <Panel title="Anomaly and matching thresholds" description="Thresholds are configuration, never hard-coded visual assumptions">
                {!can('configure') ? <PermissionDenied missing="threshold configuration" /> : (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {THRESHOLDS.map(item => (
                      <Field key={item.key} id={`t-${item.key}`} label={`${item.label} (${item.unit})`}
                        type="number" value={values[item.key]} error={errors[item.key]}
                        onChange={value => { setValues(prev => ({ ...prev, [item.key]: value })); setSaved(null); }} />
                    ))}
                  </div>
                )}
              </Panel>

              <div className="space-y-4">
                <Panel title="Rule families">
                  <dl>
                    {ANOMALY_RULES.map(rule => (
                      <KeyValue key={rule.id} label={<span className="font-mono text-[12px]">{rule.id}</span>}>
                        <span><span className="block text-[12.5px] text-fg">{rule.family}</span>
                          <span className="block text-[12px] text-fg-subtle">{rule.example}</span></span>
                      </KeyValue>
                    ))}
                  </dl>
                </Panel>
                <Panel title="Confidence display rules">
                  <dl>
                    {CONFIDENCE_DIMENSIONS.map(item => (
                      <KeyValue key={item.key} label={item.label}>{item.hint}</KeyValue>
                    ))}
                  </dl>
                  <div className="mt-3">
                    <Note tone="warning" icon={TriangleAlert}>
                      Dimensions are never blended into a single trust badge, and are not comparable until calibrated
                      against labelled data.
                    </Note>
                  </div>
                </Panel>
              </div>
            </div>
          )}

          {tab === 'users' && (
            <Panel title="Users and roles" description="Least privilege; role changes are audited">
              {!can('configure') ? <PermissionDenied missing="role administration" /> : (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {Object.entries(PERMISSIONS).map(([roleId, permissions]) => (
                    <div key={roleId} className="rounded-[8px] border border-border p-4">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-semibold text-fg">{ROLES[roleId].label}</span>
                        {role.id === roleId && <Badge tone="accent">your role</Badge>}
                      </div>
                      <p className="mt-1 text-[12.5px] leading-snug text-fg-subtle">{ROLES[roleId].blurb}</p>
                      <ul className="mt-3 space-y-1">
                        {['view', 'inspect', 'annotate', 'merge', 'approve', 'configure', 'ingest'].map(capability => (
                          <li key={capability} className="flex items-center gap-2 text-[12.5px]">
                            {permissions[capability]
                              ? <Check className="size-3.5 text-healthy" />
                              : <X className="size-3.5 text-fg-subtle" />}
                            <span className={permissions[capability] ? 'text-fg' : 'text-fg-subtle'}>
                              {capability === 'merge' ? 'merge or split incident' : capability}
                            </span>
                          </li>
                        ))}
                        <li className="flex items-center gap-2 text-[12.5px]">
                          <Check className="size-3.5 text-healthy" />
                          <span className="text-fg">audit history: {permissions.auditRead === 'subset' ? 'read-only subset' : 'full'}</span>
                        </li>
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          )}

          {tab === 'connectors' && (
            <Panel title="Connector settings" description="Managed by secret reference, never stored in plaintext">
              <Note>
                <span className="flex flex-wrap items-center gap-1.5">
                  <ShieldCheck className="size-3.5 text-healthy" />
                  <strong className="text-fg">Credentials live in environment configuration.</strong>
                </span>
                <span className="mt-1.5 block">
                  Settings records hold only a reference name such as <span className="font-mono text-[12px]">NEUTRAL_PROVIDER_TOKEN</span>{' '}
                  alongside the state (configured, missing or invalid). Values are never written to settings rows, never
                  returned by an API, and never logged.
                </span>
              </Note>
              <dl className="mt-4">
                <KeyValue label="Reference scheme" mono>env://{'{PROVIDER}_{SERVICE}_TOKEN'}</KeyValue>
                <KeyValue label="Rotation">External to this application; a rotation produces a credential state change in the audit trail.</KeyValue>
                <KeyValue label="Storage">Environment or secret manager only. No secret value is committed to the repository.</KeyValue>
                <KeyValue label="Demo safeguard">An explicit mode prevents accidental calls to paid or restricted APIs.</KeyValue>
              </dl>
            </Panel>
          )}

          {tab === 'retention' && (
            <Panel title="Retention and redaction policy" description="Durations pending owner approval">
              <Note tone="warning" icon={TriangleAlert}>
                <strong className="text-fg">TBD, pending product and data owner approval.</strong> No retention duration is
                asserted here, and no automated deletion is enabled.
              </Note>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {[
                  { label: 'Canonical events', value: 'TBD', note: 'Immutable facts, retained separately from mutable incident state' },
                  { label: 'Citizen report text', value: 'Minimised', note: 'Pseudonymised reporter identifiers; attachments restricted by role' },
                  { label: 'Raw payloads', value: 'TBD', note: 'Retained per policy with secrets and personal data redacted' },
                  { label: 'Audit records', value: 'Immutable', note: 'Not editable through any application workflow' },
                  { label: 'Graph projections', value: 'Reconcilable', note: 'Idempotent writes; the operational store stays the source of truth' },
                  { label: 'Exports', value: 'Redacted', note: 'Configured to exclude restricted fields' }
                ].map(item => (
                  <div key={item.label} className="rounded-[8px] border border-border p-3.5">
                    <div className="text-[12px] text-fg-subtle">{item.label}</div>
                    <div className="mt-1 text-[14px] font-semibold text-fg">{item.value}</div>
                    <p className="mt-1 text-[12px] leading-snug text-fg-muted">{item.note}</p>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {tab === 'audit' && (
            <Panel title="Audit log" description="Immutable by application; filterable by actor, action and time" bodyClassName="p-0">
              <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
                <div className="w-[180px]">
                  <label className="sr-only" htmlFor="actor-filter">Filter by actor</label>
                  <Select value={auditFilter.actor} onValueChange={value => setAuditFilter(prev => ({ ...prev, actor: value }))}>
                    <SelectTrigger id="actor-filter"><SelectValue placeholder="Any actor" /></SelectTrigger>
                    <SelectContent>{actors.map(item => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="w-[200px]">
                  <label className="sr-only" htmlFor="action-filter">Filter by action</label>
                  <Select value={auditFilter.action} onValueChange={value => setAuditFilter(prev => ({ ...prev, action: value }))}>
                    <SelectTrigger id="action-filter"><SelectValue placeholder="Any action" /></SelectTrigger>
                    <SelectContent>{actions.map(item => <SelectItem key={item} value={item}>{item.replace(/_/g, ' ').toLowerCase()}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <span className="ml-auto text-[12.5px] text-fg-subtle tabular-nums">{auditRows.length} of {audit.length} records</span>
              </div>

              <DataTable
                rowId={row => row.id}
                empty={<EmptyState title="No audit records" body="No record matches this filter combination." />}
                columns={[
                  { key: 'at', label: 'Timestamp', render: row => <span className="text-[12.5px] tabular-nums">{clock(row.at)}</span> },
                  { key: 'actor', label: 'Actor', render: row => (
                    <span><span className="block text-[13px] text-fg">{row.actor}</span>
                      <span className="block text-[12px] text-fg-subtle">{row.actor_role}</span></span>
                  ) },
                  { key: 'object', label: 'Object', render: row => <span className="font-mono text-[12px]">{row.object_type}:{row.object_id}</span> },
                  { key: 'action', label: 'Action', render: row => <Badge tone="neutral">{row.action.replace(/_/g, ' ').toLowerCase()}</Badge> },
                  { key: 'summary', label: 'Change', render: row => (
                    <span><span className="block text-[13px] text-fg-muted">{row.summary}</span>
                      {row.reason && <span className="block text-[12px] text-fg-subtle">reason: {row.reason}</span>}</span>
                  ) },
                  { key: 'request_id', label: 'Request', render: row => <span className="font-mono text-[12px] text-fg-subtle">{row.request_id}</span> }
                ]}
                rows={auditRows}
              />

              <div className="border-t border-border px-4 py-3">
                <TextArea label="Attempt to modify an audit record" value="" onChange={() => {}} rows={2} disabled
                  placeholder="This control is intentionally inert: audit entries cannot be edited or deleted through any application workflow." />
                <div className="mt-2"><Badge tone="neutral"><Lock />No edit or delete path is exposed for audit records</Badge></div>
              </div>
            </Panel>
          )}
        </motion.div>
      </PageBody>
    </div>
  );
}