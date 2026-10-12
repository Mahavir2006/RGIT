// Single source of truth for the agent roster.
//
// Floor positions are fixed so two operators always read the same layout, and the snapshot
// builder and the 3D floor both import from here rather than restating the roster.
//
// The agent set maps to the specialist roles in the product specification: an orchestrator
// control plane plus the specialists, and the deterministic services that stay authoritative
// for validation, deduplication and thresholds.

export const AGENTS = [
  {
    id: 'ingest',
    name: 'Ingestion',
    role: 'Adapters, normalisation, replay and live connectors',
    position: [-7.5, -2.6],
    guards: 'Never calls an LLM for a sensor event.'
  },
  {
    id: 'signal',
    name: 'Signal Intelligence',
    role: 'Anomalies, data quality and signal reliability',
    position: [-2.5, -2.6],
    guards: 'Cannot change raw events.'
  },
  {
    id: 'validate',
    name: 'Deterministic core',
    role: 'Validation, quarantine and deduplication',
    position: [2.5, -2.6],
    guards: 'Authoritative over any narrative.'
  },
  {
    id: 'fuse',
    name: 'Incident fusion',
    role: 'Candidate matching and evidence links',
    position: [7.5, -2.6],
    guards: 'Keeps contradictions visible.'
  },
  {
    id: 'causal',
    name: 'Causal & Cascade Analysis',
    role: 'Competing hypotheses and cascade paths',
    position: [-7.5, 1.4],
    guards: 'No unsupported proof claim; explicit insufficient-evidence path.'
  },
  {
    id: 'respond',
    name: 'Impact & Response',
    role: 'Affected services and ranked options',
    position: [-2.5, 1.4],
    guards: 'Suggestions only, approval required.'
  },
  {
    id: 'provenance',
    name: 'Provenance ledger',
    role: 'Observed-at versus received-at, mode and units',
    position: [2.5, 1.4],
    guards: 'Preserves original units and payload references.'
  },
  {
    id: 'monitor',
    name: 'Source health',
    role: 'Freshness, faults and missing signals',
    position: [7.5, 1.4],
    guards: 'Absence of data is never evidence of safety.'
  }
];

export const AGENT_IDS = AGENTS.map(agent => agent.id);

export const AGENT_META = Object.fromEntries(AGENTS.map(agent => [agent.id, agent]));

export const AGENT_LAYOUT = Object.fromEntries(AGENTS.map(agent => [agent.id, agent.position]));

// Who hands work to whom.
export const UPSTREAM = {
  ingest: 'hub', signal: 'ingest', validate: 'ingest', fuse: 'validate',
  causal: 'fuse', respond: 'causal', provenance: 'validate', monitor: 'ingest'
};

export const CONNECTED = {
  ingest: ['signal', 'validate', 'monitor'],
  signal: ['validate', 'fuse'],
  validate: ['fuse', 'provenance'],
  fuse: ['causal'],
  causal: ['respond'],
  respond: [],
  provenance: ['causal'],
  monitor: ['validate']
};

export const ORCHESTRATOR = {
  id: 'orchestrator',
  name: 'Orchestrator',
  role: 'Routes work · holds the approval gate',
  guards: 'No dispatch path. Nothing is actuated or published.'
};

export const STATUS_ORDER = ['idle', 'working', 'waiting', 'attention', 'complete'];

export const STATUS_LABEL = {
  idle: 'Idle',
  working: 'Working',
  waiting: 'Waiting on approval',
  attention: 'Needs attention',
  complete: 'Complete'
};
