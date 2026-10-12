// Derives live agent state from the seeded scenario dataset.
//
// Nothing here is invented per frame. Each agent's status, task and evidence come from the
// same canonical events, anomalies, hypotheses and actions the rest of the console renders,
// so the floor can never drift from the underlying data.
//
// Scrubbing the scenario clock genuinely rewinds what the agents have observed: events are
// filtered by observed-at against the replay position before anything is counted.
import { useEffect, useMemo, useState } from 'react';
import { EVENTS, ANOMALIES, HYPOTHESES, ACTIONS, INCIDENTS, buildStore } from '@/data/scenario.js';
import { evidenceFor } from '@/data/graph.js';
import { AGENT_IDS, UPSTREAM } from './agents.js';

const WINDOW_START = Date.parse('2026-10-12T13:20:00+05:30');
const WINDOW_END = Date.parse('2026-10-12T14:06:50+05:30');

const PHASE_MARK = { idle: '○', working: '●', waiting: '●', complete: '✓', attention: '⚠' };

// The graph is built once for the session; it is read-only for every snapshot.
let cachedStore = null;
function store() {
  if (!cachedStore) cachedStore = buildStore();
  return cachedStore;
}

const clip = (value, max) => (String(value || '').length > max ? `${String(value).slice(0, max - 1)}…` : String(value || ''));

export function buildSnapshot(replayProgress) {
  const graph = store();
  const progress = Math.max(0, Math.min(100, replayProgress ?? 100));
  const cutoff = WINDOW_START + ((WINDOW_END - WINDOW_START) * progress) / 100;

  const visible = EVENTS.filter(event => {
    const observed = Date.parse(event.event_time);
    return !Number.isNaN(observed) && observed <= cutoff;
  });

  const accepted = visible.filter(event => !event.validation || ['ACCEPTED', 'ACCEPTED_WITH_WARNING'].includes(event.validation.outcome));
  const quarantined = visible.filter(event => event.validation && ['QUARANTINED', 'REJECTED'].includes(event.validation.outcome));
  const duplicates = visible.filter(event => event.duplicate_of);
  const late = visible.filter(event => event.quality.flags.includes('OUT_OF_ORDER'));
  const stale = visible.filter(event => event.quality.flags.includes('MISSING_SIGNAL') || event.quality.status === 'STALE');
  const sourceCount = new Set(visible.map(event => event.source_id)).size;

  const anomalies = ANOMALIES.filter(anomaly => {
    const at = Date.parse(anomaly.detected_at);
    return !Number.isNaN(at) && at <= cutoff;
  });

  const pendingApproval = ACTIONS.filter(action => ['NEEDS_REVIEW', 'PROPOSED'].includes(action.status));

  const primary = INCIDENTS[0];
  const primaryEvidence = evidenceFor(graph, primary.incident_id);
  const supporting = primaryEvidence.filter(edge => edge._type === 'SUPPORTS');
  const contradicting = primaryEvidence.filter(edge => edge._type === 'CONTRADICTS');
  const ranked = [...primaryEvidence].sort((a, b) => (b.score || 0) - (a.score || 0));
  const leading = [...HYPOTHESES].filter(item => item.status !== 'INSUFFICIENT_EVIDENCE')
    .sort((a, b) => b.confidence - a.confidence)[0];
  const insufficient = HYPOTHESES.filter(item => item.status === 'INSUFFICIENT_EVIDENCE');

  const agents = {
    ingest: {
      status: quarantined.length ? 'attention' : 'working',
      task: quarantined.length
        ? `Rejected ${quarantined.length} invalid record${quarantined.length > 1 ? 's' : ''} with reason codes`
        : `Ingested ${visible.length} event${visible.length === 1 ? '' : 's'} from ${sourceCount} source${sourceCount === 1 ? '' : 's'}`,
      summary: `${accepted.length} canonical · ${duplicates.length} duplicate`,
      tool: 'adapter',
      count: visible.length,
      events: [
        ...visible.slice(-2).map(event => ({ action: 'received', summary: `${event.event_id} · ${event.event_type.replace(/_/g, ' ')}` })),
        ...quarantined.slice(-1).map(event => ({ action: 'quarantined', summary: `${event.event_id} · ${event.validation.reasonCode}` }))
      ],
      packetId: visible.length ? `ingest-${visible.length}` : null,
      from: UPSTREAM.ingest
    },

    signal: {
      status: anomalies.length ? 'working' : 'idle',
      task: anomalies.length
        ? `Summarising ${anomalies.length} anomal${anomalies.length === 1 ? 'y' : 'ies'} and signal reliability`
        : 'No anomalies inside the current window',
      summary: clip(anomalies[0]?.explanation, 78),
      tool: 'anomaly',
      count: anomalies.length,
      events: anomalies.slice(-3).map(item => ({ action: item.family, summary: `${item.anomaly_id} · ${item.rule_id}` })),
      packetId: anomalies.length ? `signal-${anomalies.length}` : null,
      from: UPSTREAM.signal
    },

    validate: {
      status: quarantined.length ? 'attention' : (duplicates.length || late.length) ? 'working' : 'idle',
      task: quarantined.length
        ? `Holding ${quarantined.length} record${quarantined.length > 1 ? 's' : ''} in quarantine for inspection`
        : duplicates.length
          ? `Linked ${duplicates.length} repeat deliver${duplicates.length > 1 ? 'ies' : 'y'} to canonical events`
          : late.length
            ? `Reconciling ${late.length} out-of-order arrival${late.length > 1 ? 's' : ''}`
            : 'Every record in window passed validation',
      summary: clip(quarantined[0]?.validation?.explanation ?? late[0]?.summary, 78),
      tool: 'validate',
      count: quarantined.length + duplicates.length + late.length,
      events: [
        ...quarantined.slice(-2).map(event => ({ action: 'quarantined', summary: `${event.event_id} · ${event.validation.reasonCode}` })),
        ...duplicates.slice(-1).map(event => ({ action: 'duplicate receipt', summary: `${event.event_id} → ${event.duplicate_of}` })),
        ...late.slice(-1).map(event => ({ action: 'reconciled', summary: `${event.event_id} arrived after the incident window` }))
      ],
      packetId: (quarantined.length + duplicates.length + late.length) ? `validate-${quarantined.length + duplicates.length + late.length}` : null,
      from: UPSTREAM.validate
    },

    fuse: {
      status: supporting.length ? 'working' : 'idle',
      task: `${primary.incident_id} grouped from ${supporting.length} supporting signal${supporting.length === 1 ? '' : 's'}`,
      summary: clip(ranked[0]?.rationale, 78),
      tool: 'fusion',
      count: primaryEvidence.length,
      events: [
        ...ranked.slice(0, 3).map(edge => ({ action: `${edge._type.toLowerCase()} ${edge.event_id}`, summary: `S=${(edge.score ?? 0).toFixed(2)}` })),
        ...contradicting.slice(0, 1).map(edge => ({ action: `contradicts ${edge.event_id}`, summary: `S=${(edge.score ?? 0).toFixed(2)}` }))
      ],
      packetId: supporting.length ? `fuse-${supporting.length}` : null,
      from: UPSTREAM.fuse
    },

    causal: {
      status: insufficient.length ? 'attention' : 'working',
      task: insufficient.length
        ? `Returned insufficient evidence for instrument fault · ${HYPOTHESES.length} hypotheses held`
        : `Comparing ${HYPOTHESES.length} competing hypotheses`,
      summary: clip(leading?.claim, 78),
      tool: 'causal',
      count: HYPOTHESES.length,
      events: [
        ...HYPOTHESES.slice(0, 3).map(item => ({
          action: item.hypothesis_id,
          summary: `confidence ${item.confidence.toFixed(2)} · ${item.evidence_for.length} support / ${item.evidence_against.length} conflict`
        })),
        ...insufficient.slice(0, 1).map(item => ({ action: 'insufficient evidence', summary: item.hypothesis_id }))
      ],
      packetId: HYPOTHESES.length ? `causal-${HYPOTHESES.length}` : null,
      from: UPSTREAM.causal
    },

    respond: {
      status: pendingApproval.length ? 'waiting' : 'idle',
      task: pendingApproval.length
        ? `${pendingApproval.length} action${pendingApproval.length > 1 ? 's' : ''} awaiting human approval`
        : 'No actions awaiting review',
      summary: clip(pendingApproval[0]?.rationale, 78),
      tool: 'response',
      count: pendingApproval.length,
      events: pendingApproval.slice(0, 3).map(item => ({
        action: `${item.action_id} · ${item.type}`,
        summary: `${item.priority} · ${item.status.replace(/_/g, ' ').toLowerCase()}`
      })),
      packetId: pendingApproval.length ? `respond-${pendingApproval.length}` : null,
      from: UPSTREAM.respond
    },

    provenance: {
      status: stale.length ? 'attention' : 'working',
      task: stale.length
        ? `${stale.length} signal${stale.length > 1 ? 's' : ''} missing — observability reduced, not assumed safe`
        : 'Tracking observed-at against received-at',
      summary: clip(stale[0]?.summary, 78),
      tool: 'provenance',
      count: stale.length,
      events: [
        ...stale.slice(0, 2).map(event => ({ action: 'missing signal', summary: clip(event.summary, 58) })),
        ...late.slice(0, 1).map(event => ({ action: 'out of order', summary: `${event.event_id} observed before ingest` }))
      ],
      packetId: stale.length ? `provenance-${stale.length}` : null,
      from: UPSTREAM.provenance
    },

    monitor: {
      status: 'working',
      task: `Watching ${sourceCount} reporting connector${sourceCount === 1 ? '' : 's'} for freshness and faults`,
      summary: `${sourceCount} of ${ACTIONS.length + 7} sources reporting in window`,
      tool: 'health',
      count: sourceCount,
      events: ANOMALIES.filter(item => ['R-HEALTH-01', 'R-DOMAIN-01'].includes(item.rule_id)).slice(-3)
        .map(item => ({ action: item.family, summary: `${item.anomaly_id} · ${clip(item.explanation, 52)}` })),
      packetId: 'monitor-health',
      from: UPSTREAM.monitor
    }
  };

  // Guarantee a state for every desk so the floor never renders a hole.
  for (const id of AGENT_IDS) {
    agents[id] ??= { status: 'idle', task: 'Idle', summary: '', tool: 'idle', count: 0, events: [], packetId: null, from: UPSTREAM[id] };
  }

  const phase = {};
  for (const id of AGENT_IDS) phase[id] = PHASE_MARK[agents[id].status] ?? '○';

  return {
    agents,
    hub: pendingApproval.length ? 'waiting' : 'idle',
    wall: {
      task: 'Monsoon waterlogging · Andheri East',
      phase,
      events: visible.length,
      pending: pendingApproval.length,
      mode: 'sim'
    }
  };
}

const WORKFLOW_AGENT_IDS = {
  signal_intelligence: 'signal',
  incident_fusion: 'fuse',
  causal_cascade: 'causal',
  impact_response: 'respond'
};

function workflowAgentState(workflow, id, run) {
  const status = run?.status === 'failed' ? 'attention' : run ? 'complete' : 'idle';
  const outputs = {
    signal: {
      task: workflow.signal_analysis?.evidence_summary || `Signal assessment ${status === 'complete' ? 'completed' : 'not run'}`,
      summary: (workflow.signal_analysis?.quality_concerns || []).map(item => item.description).join(' · '),
      count: workflow.signal_analysis?.extracted_facts?.length || 0,
      events: (workflow.signal_analysis?.extracted_facts || []).slice(0, 3).map(item => ({ action: item.event_id || 'signal fact', summary: item.statement || '' }))
    },
    fuse: {
      task: `${workflow.fusion_decisions?.length || 0} event association${workflow.fusion_decisions?.length === 1 ? '' : 's'} evaluated`,
      summary: workflow.fusion_decisions?.[0]?.reason || '',
      count: workflow.fusion_decisions?.length || 0,
      events: (workflow.fusion_decisions || []).slice(0, 3).map(item => ({ action: item.event_id || 'association', summary: `${item.decision || ''}${item.selected_incident_id ? ` · ${item.selected_incident_id}` : ''}` }))
    },
    causal: {
      task: `${workflow.hypotheses?.length || 0} hypotheses · ${workflow.cascade_scenarios?.length || 0} cascade scenarios`,
      summary: workflow.hypotheses?.[0]?.claim || '',
      count: (workflow.hypotheses?.length || 0) + (workflow.cascade_scenarios?.length || 0),
      events: [
        ...(workflow.hypotheses || []).slice(0, 2).map(item => ({ action: item.hypothesis_id || 'hypothesis', summary: item.claim || item.status || '' })),
        ...(workflow.cascade_scenarios || []).slice(0, 1).map(item => ({ action: item.scenario_id || 'cascade scenario', summary: `${item.affected_asset_ids?.length || 0} affected assets${item.risk_score != null ? ` · risk ${item.risk_score}` : ''}` }))
      ]
    },
    respond: {
      task: workflow.operator_summary || `${workflow.candidate_actions?.length || 0} response options prepared`,
      summary: workflow.severity_assessment?.explanation || '',
      count: workflow.candidate_actions?.length || 0,
      events: (workflow.candidate_actions || []).slice(0, 3).map(item => ({ action: item.action_id || 'response option', summary: item.action_description || '' }))
    }
  }[id];
  return {
    ...outputs,
    status,
    tool: 'intelligence workflow',
    from: UPSTREAM[id],
    packetId: run?.run_id || null,
    ...(run?.fallback_used ? { summary: `${outputs.summary}${outputs.summary ? ' · ' : ''}Deterministic fallback used` } : {}),
    ...(run?.error ? { summary: `${outputs.summary}${outputs.summary ? ' · ' : ''}${run.error}` } : {})
  };
}

function withWorkflow(snapshot, workflow) {
  if (!workflow?.workflow_id) return snapshot;
  const runs = Object.fromEntries((workflow.agent_runs || []).map(run => [run.agent_name, run]));
  const agents = { ...snapshot.agents };
  for (const [workflowName, kitchenId] of Object.entries(WORKFLOW_AGENT_IDS)) {
    const run = runs[workflowName];
    agents[kitchenId] = workflowAgentState(workflow, kitchenId, run);
    if (!run && workflow.status === 'running') {
      const pending = ['signal_intelligence', 'incident_fusion', 'causal_cascade', 'impact_response']
        .find(name => !runs[name] && !(name === 'signal_intelligence' && workflow.skip_signal) && !(name === 'incident_fusion' && workflow.skip_fusion));
      if (pending === workflowName) {
        agents[kitchenId] = { ...agents[kitchenId], status: 'working', task: 'Processing workflow evidence' };
      } else if ((workflowName === 'signal_intelligence' && workflow.skip_signal) || (workflowName === 'incident_fusion' && workflow.skip_fusion)) {
        agents[kitchenId] = { ...agents[kitchenId], task: 'Skipped by workflow routing rules' };
      }
    }
  }
  const events = snapshot.wall.events;
  return {
    ...snapshot,
    agents,
    hub: workflow.review_required ? 'waiting' : snapshot.hub,
    wall: { ...snapshot.wall, task: workflow.incident_id || 'Latest intelligence workflow', events, mode: 'live' },
    workflow
  };
}

export function useKitchenSnapshot(replayProgress) {
  const [workflow, setWorkflow] = useState(null);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch('/api/v1/intelligence/workflows/latest', { cache: 'no-store' });
        if (!response.ok) throw new Error(`API returned ${response.status}`);
        const next = await response.json();
        if (active) setWorkflow(next.workflow_id ? next : null);
      } catch {
        if (active) setWorkflow(null);
      }
    };
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => { active = false; clearInterval(timer); };
  }, []);
  return useMemo(() => withWorkflow(buildSnapshot(replayProgress), workflow), [replayProgress, workflow]);
}
