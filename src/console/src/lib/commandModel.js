// Projects the incident store into the flat, filterable shape the command map consumes.
//
// One projection, used by the map, the counters and the list, is what keeps those three views
// from drifting. The projection also computes the emergency-access road states, because a road
// status is a derived fact about incidents rather than something stored independently.
import { useMemo } from 'react';
import { buildStore, INCIDENTS, CANDIDATES, ANOMALIES, ACTIONS, EVENTS } from '../data/scenario.js';
import { evidenceFor, incidentAssets } from '../data/graph.js';
import { categoryForEventType, categoryForIncidentType } from '../data/taxonomy.js';
import { normaliseSeverity } from '../data/canonical.js';
import { deriveAccessStates, evidenceStateOf } from './filters.js';
import { ASSETS } from '../data/geo.js';

// Access-evidence class per incident. This is the difference between "a sensor read zero" and
// "a neighbour complained", and the emergency overlay renders them differently on purpose.
const ACCESS_EVIDENCE = {
  'INC-104': { class: 'observed', source: 'Road camera + citizen report' },
  'INC-103': { class: 'reported', source: 'Citizen report' },
  'INC-101': { class: 'modelled', source: 'Station baseline' }
};

export function useCommandModel(liveEvents = []) {
  return useMemo(() => buildCommandModel(liveEvents), [liveEvents]);
}

export function buildCommandModel(liveEvents = []) {
  const store = buildStore();

  // Live connector output is merged in as extra events. They are normalised upstream, so here
  // they only contribute evidence counts and are always badged with their own data mode.
  const allEvents = [...EVENTS, ...liveEvents];

  const candidates = CANDIDATES.map(candidate => ({
    ...candidate,
    severity: normaliseSeverity(candidate.severity),
    category: candidate.category ?? 'reports',
    mode: 'SIMULATED',
    sourceTypes: ['citizen'],
    supporting: candidate.event_count ?? 0,
    contradicting: 0,
    stale: false,
    confidence: 0.42
  }));

  const incidents = INCIDENTS.map(incident => {
    const evidence = evidenceFor(store, incident.incident_id);
    const supporting = evidence.filter(edge => edge._type === 'SUPPORTS').length;
    const contradicting = evidence.filter(edge => edge._type === 'CONTRADICTS').length;
    const contextual = evidence.filter(edge => edge._type === 'CONTEXT_FOR').length;

    const eventIds = evidence.map(edge => edge._from);
    const related = allEvents.filter(event => eventIds.includes(event.event_id));
    const sourceTypes = [...new Set(related.map(event => event.source_type).filter(Boolean))];
    const categories = [...new Set(related.map(event => event.category ?? categoryForEventType(event.event_type)))];

    // Sensor health and missing-signal records make this incident's picture incomplete.
    const stale = related.some(event => event.quality?.status === 'STALE'
      || event.quality?.flags?.includes('MISSING_SIGNAL'));

    const assets = incidentAssets(store, incident.incident_id).map(edge => store.find('Asset', edge._to)).filter(Boolean);
    const dependencies = store.edges.filter(edge => edge._fromLabel === 'Asset' && edge._from === assets[0]?.asset_id);
    const roadAssets = assets.filter(asset => ['ROAD_SEGMENT', 'UNDERPASS'].includes(asset.type)).map(asset => asset.asset_id);

    // Cascades are a modelled consequence, never an observation.
    const hasCascade = incident.incident_id === 'INC-104';
    // The incident's own type decides its category. Evidence categories are still kept, so an
    // operator can see that a flooding incident is also driven by weather and drainage signals.
    const category = categoryForIncidentType(incident.type)
      ?? categories[0]
      ?? 'reports';
    const allCategories = [...new Set([category, ...categories])];

    const item = {
      id: incident.incident_id,
      title: incident.title,
      type: incident.type,
      category,
      categories: allCategories,
      severity: normaliseSeverity(incident.severity),
      status: incident.status === 'RESOLVED' || incident.status === 'CLOSED' ? 'RESOLVED'
        : incident.status === 'INVESTIGATING' || incident.status === 'MITIGATING' ? 'INVESTIGATING'
          : incident.status === 'ACKNOWLEDGED' ? 'ESCALATED' : 'CONFIRMED',
      rawStatus: incident.status,
      areaName: incident.area_name,
      lat: incident.lat,
      lon: incident.lon,
      locationPrecision: incident.location_precision,
      uncertaintyM: incident.location_uncertainty_m,
      radiusM: incident.impacted_radius_m,
      observedAt: incident.first_seen_at,
      updatedAt: incident.updated_at,
      createdAt: incident.created_at,
      mode: 'SIMULATED',
      sourceTypes: sourceTypes.length ? sourceTypes : ['iot'],
      supporting,
      contradicting,
      contextual,
      stale,
      confidence: incident.confidence.membership,
      confidenceDimensions: incident.confidence,
      summary: incident.summary,
      expectedSignals: incident.expected_signals,
      evidence: related,
      assets,
      roadAssets,
      dependencyCount: dependencies.length,
      anomalyIds: ANOMALIES.filter(anomaly => related.some(event => event.event_id === anomaly.event_id)).map(anomaly => anomaly.anomaly_id),
      actionIds: ACTIONS.filter(action => action.incident_id === incident.incident_id).map(action => action.action_id),
      hypothesisIds: store.all('Hypothesis').filter(item2 => item2.incident_id === incident.incident_id).map(item2 => item2.hypothesis_id),
      isPredicted: false,
      // Evidence state is derived once here so the map ring, the list badge and the inspector
      // can never disagree about whether this record is supported, conflicting or stale.
      evidence: evidenceStateOf({ supporting, contradicting, stale }),
      accessEvidence: ACCESS_EVIDENCE[incident.incident_id]?.class ?? 'modelled',
      accessSource: ACCESS_EVIDENCE[incident.incident_id]?.source ?? 'Modelled dependency',
      accessObservedAt: incident.updated_at,
      impactsRoads: roadAssets
    };

    // A predicted cascade is surfaced as its own item so the operator can filter it
    // separately from observed incidents. It is always labelled as modelled.
    const cascadeItems = hasCascade ? [{
      id: 'CAS-104-1',
      title: 'Predicted emergency-access delay via S-13',
      type: 'Cascade risk',
      category: 'cascade',
      categories: ['cascade'],
      severity: 'MODERATE',
      status: 'NEW',
      rawStatus: 'PREDICTED',
      areaName: incident.area_name,
      lat: incident.lat + 0.004,
      lon: incident.lon - 0.006,
      radiusM: 1400,
      observedAt: incident.updated_at,
      updatedAt: incident.updated_at,
      mode: 'SIMULATED',
      sourceTypes: ['iot'],
      supporting: 3,
      contradicting: 1,
      contextual: 0,
      stale: false,
      confidence: 0.38,
      summary: 'Modelled chain: rainfall → drainage overload → waterlogging → reduced road capacity → congestion → emergency-access delay.',
      evidence: related.slice(0, 3),
      assets: [],
      roadAssets: ['AST-ANDH-ROAD-SEG-13'],
      isPredicted: true,
      evidence: 'CONFLICTING',
      // The cascade's own extent is modelled, so it carries a stated uncertainty equal to its
      // radius. Without it the prediction would draw as a confident point.
      uncertaintyM: 1400,
      locationPrecision: 'area',
      accessEvidence: 'modelled',
      accessSource: 'Cascade model',
      accessObservedAt: incident.updated_at,
      impactsRoads: ['AST-ANDH-ROAD-SEG-13'],
      expectedSignals: [],
      anomalyIds: [],
      actionIds: [],
      hypothesisIds: []
    }] : [];

    return [item, ...cascadeItems];
  }).flat();

  // Road segments come from the asset table so the access overlay and the map share geometry.
  const roads = ASSETS
    .filter(asset => ['ROAD_SEGMENT', 'UNDERPASS'].includes(asset.type))
    .map(asset => ({
      id: asset.asset_id,
      name: asset.name,
      lat: asset.lat,
      lon: asset.lon,
      type: asset.type,
      lastObservedAt: asset.freshness
    }));

  const accessStates = deriveAccessStates(roads, incidents);

  return {
    store,
    incidents,
    candidates,
    roads,
    accessStates,
    assets: ASSETS,
    anomalies: ANOMALIES,
    actions: ACTIONS,
    events: allEvents
  };
}

/** Everything on screen derives its evidence state from here, so the badges never disagree. */
export function evidenceState(item) {
  return evidenceStateOf(item);
}