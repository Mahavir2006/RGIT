import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Search, Download } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { Panel, Badge, Button, Input, DataTable, Chips, EmptyState, UncalibratedNote } from '@/components/blocks.jsx';
import { useApp } from '@/lib/store.jsx';
import { evidenceFor } from '@/data/graph.js';
import { ago } from '@/lib/format.js';

function severityTone(severity) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'critical';
  if (severity === 'MODERATE') return 'degraded';
  return 'neutral';
}

export default function IncidentList() {
  const { store, incidents, area } = useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [severity, setSeverity] = useState(params.get('severity') || 'ALL');
  const [status, setStatus] = useState('ALL');
  const [query, setQuery] = useState('');

  const rows = useMemo(() => incidents
    .filter(item => area === 'All areas' || item.area_name === area)
    .filter(item => severity === 'ALL' || item.severity === severity)
    .filter(item => status === 'ALL' || item.status === status)
    .filter(item => !query || `${item.incident_id} ${item.title} ${item.type} ${item.area_name}`.toLowerCase().includes(query.toLowerCase()))
    .map(item => ({
      ...item,
      supporting: evidenceFor(store, item.incident_id).filter(edge => edge._type === 'SUPPORTS').length,
      contradicting: evidenceFor(store, item.incident_id).filter(edge => edge._type === 'CONTRADICTS').length
    })), [incidents, store, area, severity, status, query]);

  return (
    <div className="min-h-full">
      <PageHeader
        title="Incidents"
        description="Operator-visible records. Validity, membership and cause confidence stay separate dimensions."
        actions={<Button variant="primary" size="md"><Download />Export bounded set</Button>}
      />

      <PageBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-[260px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle" />
            <Input value={query} onChange={event => setQuery(event.target.value)}
              placeholder="Search id, title or area" aria-label="Search incidents" className="pl-8" />
          </div>
          <Chips label="Severity" ariaLabel="Severity filter" options={['ALL', 'CRITICAL', 'HIGH', 'MODERATE', 'LOW']} value={severity} onChange={setSeverity} />
          <Chips label="Status" ariaLabel="Status filter" options={['ALL', 'CANDIDATE', 'OPEN', 'ACKNOWLEDGED', 'INVESTIGATING', 'MITIGATING', 'RESOLVED', 'CLOSED']} value={status} onChange={setStatus} />
          <span className="ml-auto text-[12.5px] text-fg-subtle tabular-nums">{rows.length} of {incidents.length}</span>
        </div>

        <Panel bodyClassName="p-0">
          <DataTable
            rowId={row => row.incident_id}
            onRowClick={row => navigate(`/incidents/${row.incident_id}`)}
            empty={<EmptyState title="No incidents match"
              body="No record matches the current area, severity, status and search combination. Clear a filter to widen the set — this is not evidence that no incident exists." />}
            columns={[
              { key: 'id', label: 'ID', render: row => <span className="text-[12.5px] font-medium text-accent tabular-nums">{row.incident_id}</span> },
              { key: 'title', label: 'Incident', render: row => (
                <span><span className="block text-[13px] font-medium text-fg">{row.title}</span>
                  <span className="block text-[12px] text-fg-subtle">{row.type} · {row.area_name}</span></span>
              ) },
              { key: 'severity', label: 'Severity', render: row => <Badge tone={severityTone(row.severity)}>{row.severity.toLowerCase()}</Badge> },
              { key: 'status', label: 'Status', render: row => <Badge tone="neutral">{row.status.replace(/_/g, ' ').toLowerCase()}</Badge> },
              { key: 'validity', label: 'Validity', align: 'right', render: row => <span className="text-[12.5px] tabular-nums">{row.confidence.validity.toFixed(2)}</span> },
              { key: 'membership', label: 'Membership', align: 'right', render: row => <span className="text-[12.5px] tabular-nums">{row.confidence.membership.toFixed(2)}</span> },
              { key: 'cause', label: 'Cause', align: 'right', render: row => <span className="text-[12.5px] tabular-nums">{row.confidence.cause.toFixed(2)}</span> },
              { key: 'evidence', label: 'Evidence', align: 'right', render: row => (
                <span className="text-[12.5px] tabular-nums"><span className="text-healthy">+{row.supporting}</span>{' '}<span className="text-critical">−{row.contradicting}</span></span>
              ) },
              { key: 'owner', label: 'Owner', render: row => row.owner ?? <span className="text-fg-subtle">Unassigned</span> },
              { key: 'updated', label: 'Updated', align: 'right', render: row => <span className="text-[12.5px] text-fg-subtle">{ago(row.updated_at)}</span> }
            ]}
            rows={rows}
          />
          <div className="border-t border-border p-4"><UncalibratedNote /></div>
        </Panel>
      </PageBody>
    </div>
  );
}