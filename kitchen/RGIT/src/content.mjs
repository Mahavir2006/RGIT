export const github = 'https://github.com/Snychng/daily-design';
export const brand = 'Urban Sentinel';
export const slogan = 'From fragmented signals to an explainable incident.';

// Product framing shown on the landing page and used as the console entry point.
export const product = {
  name: 'Urban Sentinel',
  tagline: 'UrbanIncident Fusion & Causal Intelligence',
  version: '1.0',
  city: 'Mumbai',
  consolePath: '/overview',
  // Replay is the default operating mode; every surface that renders it must label it.
  defaultMode: 'SYNTHETIC REPLAY',
  modeNote: 'Decision support for human review. Not an autonomous dispatch authority.'
};

// The Work wall carries the fourteen system surfaces of the product: the five recommended
// differentiators, the six specialist agents, and the three cross-cutting engines.
// Tags must stay substring-matchable by the work filter chips (see scripts/build.mjs).
export const studies = [
  ['Cascade Predictor', 'dispersion', '5ad1ff', 'fusion, causal', 'Estimates how drainage overload propagates into road blockage and emergency-access delay. Every link is labelled as a hypothesis, never as proven cause.'],
  ['Missing-Signal Intelligence', 'genesis', '7fd4c1', 'sources, audit', 'Detects sensors that have gone silent or stale and lowers observability confidence instead of reading absence as safety.'],
  ['Contradiction-Aware Fusion', 'orbit', 'e0574f', 'fusion, causal', 'Keeps conflicting citizen, news, vision and sensor evidence visible rather than majority-voting it away.'],
  ['Explainable Evidence Graph', 'star-ring', '9a8cf5', 'causal, fusion', 'Shows which observations support or contradict each possible cause, with provenance, timestamp and score contribution.'],
  ['Risk-Based What-If Engine', 'slingshot', 'f5a524', 'response, causal', 'Compares candidate interventions against explicit assumptions, resource cost, side effects and estimated risk reduction.'],
  ['Orchestrator', 'gallery', '4a9de0', 'fusion, audit', 'Routes analysis tasks, manages state, retries and approval gates. Holds the explicit failure path; never dispatches.'],
  ['Signal Intelligence', 'dispersion', '38bdf8', 'sources, fusion', 'Summarises anomalies, data quality and signal reliability from validated events with evidence identifiers attached.'],
  ['Incident Fusion', 'orbit', 'a78bfa', 'fusion', 'Explains candidate membership and alternative groupings. Deterministic scoring rules stay authoritative over the narrative.'],
  ['Causal Specialist', 'star-ring', 'f472b6', 'causal, fusion', 'Generates competing causal hypotheses and traces potential cascade paths, surfacing assumptions and unknowns.'],
  ['Impact Response', 'slingshot', '34d399', 'response, causal', 'Summarises affected services and ranks response options with rationale, trade-offs and approval requirements.'],
  ['Deterministic Core', 'genesis', '8fa2b8', 'audit, sources', 'Validation, unit normalisation, deduplication, threshold checks and candidate retrieval, all reproducible for a fixed dataset.'],
  ['Provenance Ledger', 'gallery', '6f8fb5', 'audit, sources', 'Preserves observed-at and received-at separately, plus source mode, original units and payload references.'],
  ['Action Ledger', 'dispersion', 'fb923c', 'response, audit', 'Records owner, priority, rationale, expected impact and uncertainty for every proposed response action.'],
  ['Permission Model', 'orbit', 'c084fc', 'audit, response', 'Least-privilege roles enforced server-side, with every approval, rejection and reassignment written to an immutable trail.']
].map(([name, cover, uiColor, tags, description], index) => ({
  id: `sentinel-module-${index + 1}`,
  name, slug: name.toLowerCase().replaceAll(' ', '-'), description,
  clientName: 'Urban Sentinel / Module',
  completionDate: '2026-10-12T00:00:00.000Z', uiColor, tags,
  priority: index + 1, projectURL: github,
  projectLogo: { url: '/assets/daily/wordmark.png', width: 520, height: 58 },
  // The WorkItem marks the active card by media URL, so every module keeps a unique URL
  // even where it reuses one of the six available cover plates.
  video: { url: `/assets/daily/study-${name.toLowerCase().replaceAll(' ', '-')}.jpg`, thumbnail: `/assets/daily/cover-${cover}.jpg` }
}));