import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, ShieldCheck } from 'lucide-react';
import { Badge, Button, Panel } from '@/components/blocks.jsx';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

export default function TrackReport() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const token = window.location.hash.slice(1);
    if (!token) {
      setError('This tracking link is missing its private access token. Ask the reporting operator for a new link.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/report-status`, {
        headers: { Authorization: `Bearer ${decodeURIComponent(token)}` }
      });
      if (!response.ok) throw new Error(response.status === 404 ? 'This tracking link is invalid or expired.' : `Status lookup failed (${response.status}).`);
      setReport(await response.json());
    } catch (cause) {
      setError(cause.message || 'The status service could not be reached. Try again shortly.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const title = report?.status?.replace(/_/g, ' ') || 'Report status';
  return (
    <main className="min-h-screen bg-canvas px-4 py-10 text-fg sm:px-6">
      <div className="mx-auto max-w-2xl space-y-5">
        <header>
          <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-[0.16em] text-accent">
            <ShieldCheck size={15} /> Urban Sentinel · secure report tracking
          </div>
          <h1 className="mt-3 text-2xl font-semibold">Track your report</h1>
          <p className="mt-2 text-[13px] leading-relaxed text-fg-muted">
            This private link shows delivery and follow-up updates from the assigned department.
          </p>
        </header>

        {error && <Panel><p role="alert" className="text-[13px] text-degraded">{error}</p></Panel>}
        {report && (
          <Panel
            title={report.department_name}
            description={`Report ${report.report_id} · incident ${report.incident_id}`}
            actions={<Badge tone={report.status === 'resolved' ? 'healthy' : 'degraded'}>{title}</Badge>}
          >
            <dl className="grid gap-4 text-[13px] sm:grid-cols-2">
              <div><dt className="text-fg-subtle">Delivery</dt><dd className="mt-1 text-fg">{report.delivery_status.replace(/_/g, ' ')}</dd></div>
              <div><dt className="text-fg-subtle">Department reference</dt><dd className="mt-1 text-fg">{report.external_reference || 'Not provided'}</dd></div>
              <div><dt className="text-fg-subtle">Submitted</dt><dd className="mt-1 text-fg">{report.submitted_at ? new Date(report.submitted_at).toLocaleString() : 'Pending'}</dd></div>
              <div><dt className="text-fg-subtle">Resolved</dt><dd className="mt-1 text-fg">{report.resolved_at ? new Date(report.resolved_at).toLocaleString() : 'Not resolved'}</dd></div>
            </dl>
            <div className="mt-5 border-t border-border pt-4">
              <h2 className="text-[13px] font-medium">Updates</h2>
              {report.status_history?.length
                ? <ol className="mt-3 space-y-3">{[...report.status_history].reverse().map((item, index) => (
                  <li key={`${item.at}-${index}`} className="border-l-2 border-accent/40 pl-3">
                    <p className="text-[12.5px] font-medium capitalize text-fg">{item.status.replace(/_/g, ' ')}</p>
                    <p className="mt-0.5 text-[11.5px] text-fg-subtle">{new Date(item.at).toLocaleString()}</p>
                    {item.note && <p className="mt-1 text-[12px] text-fg-muted">{item.note}</p>}
                  </li>
                ))}</ol>
                : <p className="mt-2 text-[12.5px] text-fg-subtle">No updates have been recorded yet.</p>}
            </div>
          </Panel>
        )}

        <div className="flex items-center justify-between gap-3 text-[11.5px] text-fg-subtle">
          <span>Only people with this link can view this report's status.</span>
          <Button variant="default" size="sm" disabled={loading} onClick={refresh}><RefreshCw />Refresh</Button>
        </div>
      </div>
    </main>
  );
}
