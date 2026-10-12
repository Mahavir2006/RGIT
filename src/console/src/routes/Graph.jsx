import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import EvidenceGraph from '@/lib/EvidenceGraph.jsx';
import { useApp } from '@/lib/store.jsx';
import { Button } from '@/components/ui';

// Dedicated full-viewport graph. Reachable from the evidence page, and deep-linkable so a
// graph can be shared or opened straight from an incident id.
export default function Graph() {
  const { incidentId } = useParams();
  const { store, incidents } = useApp();
  const navigate = useNavigate();
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [showContradictions, setShowContradictions] = useState(true);

  // /graph without an id resolves to the most severe open incident, so the route is useful
  // on its own rather than only as a deep link.
  const resolvedId = incidentId
    ?? [...incidents].sort((a, b) => (['CRITICAL', 'HIGH', 'MODERATE', 'LOW'].indexOf(a.severity) - ['CRITICAL', 'HIGH', 'MODERATE', 'LOW'].indexOf(b.severity)))[0]?.incident_id;

  const incident = resolvedId ? store.find('Incident', resolvedId) : null;
  if (!incident) {
    return (
      <div className="grid h-full place-items-center px-6 text-center">
        <div>
          <div className="text-[15px] font-medium text-fg">No incident to graph</div>
          <p className="mt-1 text-[13px] text-fg-muted">{incidentId} has no evidence graph.</p>
          <Button className="mt-3" onClick={() => navigate('/incidents')}>Back to incidents</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden bg-[#0b0f17]">
      {/* Only the side rail is visible on this route, so the controls live inside the graph. */}
      <label className="absolute right-4 top-4 z-20 inline-flex h-9 items-center gap-2 rounded-lg border border-slate-800 bg-[#111827]/95 px-3 text-[12.5px] text-slate-300 backdrop-blur">
        <input
          type="checkbox"
          checked={showContradictions}
          onChange={event => setShowContradictions(event.target.checked)}
          className="accent-[#22d3ee]"
        />
        Show contradictions
      </label>

      <EvidenceGraph
        store={store}
        incidentId={incident.incident_id}
        showContradictions={showContradictions}
        selectedEvent={selectedEvent}
        onSelectEvent={setSelectedEvent}
        fill
      />
    </div>
  );
}