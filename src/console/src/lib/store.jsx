// Application state: the graph store, session/role, global filters and simulated source
// health. Mutations here are UI-only; there is no backend in this prototype.
import { createContext, useContext, useMemo, useReducer, useCallback } from 'react';
import { buildStore, EVENTS, INCIDENTS, AUDIT } from '../data/scenario.js';
import { SOURCES } from '../data/sources.js';
import { STATUS_TRANSITIONS, ACTION_TRANSITIONS } from '../data/graph.js';

const AppContext = createContext(null);

export const ROLES = {
  VIEWER: { id: 'VIEWER', label: 'Viewer', blurb: 'Read-only dashboards, scenarios and provenance.' },
  ANALYST: { id: 'ANALYST', label: 'Operations analyst', blurb: 'Triage, annotate, and merge or split with a reason.' },
  SUPERVISOR: { id: 'SUPERVISOR', label: 'Incident commander', blurb: 'Approve or decline suggested response actions.' },
  ADMIN: { id: 'ADMIN', label: 'System administrator', blurb: 'Manage roles, thresholds, connectors and retention.' },
  PLATFORM: { id: 'PLATFORM', label: 'Data / platform operator', blurb: 'Diagnose stale feeds, trigger sync, inspect errors.' }
};

export const PERMISSIONS = {
  VIEWER: { view: true, inspect: true, annotate: false, merge: false, approve: false, configure: false, ingest: false, auditRead: 'subset' },
  ANALYST: { view: true, inspect: true, annotate: true, merge: true, approve: false, configure: false, ingest: false, auditRead: true },
  SUPERVISOR: { view: true, inspect: true, annotate: true, merge: true, approve: true, configure: false, ingest: false, auditRead: true },
  ADMIN: { view: true, inspect: true, annotate: true, merge: true, approve: true, configure: true, ingest: true, auditRead: true },
  PLATFORM: { view: true, inspect: true, annotate: false, merge: false, approve: false, configure: false, ingest: true, auditRead: true }
};

const initialState = {
  store: buildStore(),
  role: 'ANALYST',
  signedIn: true,
  timeWindow: '60m',
  area: 'All areas',
  search: '',
  // Layer keys are shared with the map's visibility pairs and the intelligence-layer panel.
  // A layer with no supplying source defaults to off so the map never implies live coverage.
  layers: {
    incidents: true, candidates: true, assets: true, impactZones: true, dependencies: true,
    emergencyAccess: true, rainfall: true, hazard: true, indicators: true,
    crowd: false, transit: false, power: false, airQuality: false,
    facilities: false, sensorHealth: false, cascadePaths: false
  },
  // Live connector output lands here and is merged into the same projection as the replayed
  // scenario, so a live record and a seeded one are filtered and drawn by one code path.
  liveEvents: [],
  // 2D indicator overlay state. Pausing freezes every CSS animation in place rather than
  // removing the indicators, so the operator keeps the information without the motion.
  fx: { paused: false, lowPerformance: false, hideUnselected: false },
  // Simulated outage state driven by the Data Sources screen.
  simulatedOutage: [],
  dismissedBanner: false,
  audit: [...AUDIT],
  incidentStatus: Object.fromEntries(INCIDENTS.map(item => [item.incident_id, item.status])),
  actionStatus: Object.fromEntries(['ACT-3001', 'ACT-3002', 'ACT-3003', 'ACT-3004', 'ACT-3005', 'ACT-3006'].map(id => [id, null])),
  annotations: [],
  replayPlaying: false,
  replayTime: 100
};

function reducer(state, action) {
  switch (action.type) {
    case 'signIn': return { ...state, signedIn: true, role: action.role };
    case 'signOut': return { ...state, signedIn: false };
    case 'setRole': return { ...state, role: action.role };
    case 'setTimeWindow': return { ...state, timeWindow: action.value };
    case 'setArea': return { ...state, area: action.value };
    case 'setSearch': return { ...state, search: action.value };
    case 'toggleLayer': return { ...state, layers: { ...state.layers, [action.layer]: !state.layers[action.layer] } };
case 'setFx': return { ...state, fx: { ...state.fx, [action.key]: action.value } };
case 'toggleFx': return { ...state, fx: { ...state.fx, [action.key]: !state.fx[action.key] } };
    case 'toggleOutage': return {
      ...state,
      simulatedOutage: state.simulatedOutage.includes(action.sourceId)
        ? state.simulatedOutage.filter(id => id !== action.sourceId)
        : [...state.simulatedOutage, action.sourceId]
    };
    case 'dismissBanner': return { ...state, dismissedBanner: true };
    case 'appendAudit': return { ...state, audit: [action.entry, ...state.audit] };
    case 'changeIncidentStatus': {
      const from = state.incidentStatus[action.incidentId];
      if (!STATUS_TRANSITIONS[from]?.includes(action.to)) return state;
      return {
        ...state,
        incidentStatus: { ...state.incidentStatus, [action.incidentId]: action.to },
        audit: [action.entry, ...state.audit]
      };
    }
    case 'changeActionStatus': {
      const id = action.actionId;
      const from = state.actionStatus[id];
      if (from && !ACTION_TRANSITIONS[from]?.includes(action.to)) return state;
      if (!from && !ACTION_TRANSITIONS.PROPOSED.includes(action.to)) return state;
      return {
        ...state,
        actionStatus: { ...state.actionStatus, [id]: action.to },
        audit: [action.entry, ...state.audit]
      };
    }
    case 'annotate': return { ...state, annotations: [...state.annotations, action.annotation], audit: [action.entry, ...state.audit] };
    case 'setReplay': return { ...state, ...action.values };
    default: return state;
  }
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // A simulated outage must visibly change source health without touching unrelated adapters.
  const sources = useMemo(() => SOURCES.map(source => {
    if (!state.simulatedOutage.includes(source.source_id)) return source;
    return { ...source, health: 'OFFLINE', lastSuccess: source.lastSuccess, simulated: true, errorClass: 'SIMULATED_OUTAGE' };
  }), [state.simulatedOutage]);

  const permissions = PERMISSIONS[state.role];
  const role = ROLES[state.role];

  const can = useCallback(capability => Boolean(permissions[capability]), [permissions]);

  const incidents = useMemo(() => state.store.all('Incident').map(incident => ({
    ...incident,
    status: state.incidentStatus[incident.incident_id]
  })), [state.store, state.incidentStatus]);

  const audit = state.audit;

  const value = useMemo(() => ({
    ...state, incidents, sources, permissions, role, can,
    events: EVENTS, dispatch,
    health: { degraded: sources.filter(s => s.health === 'DEGRADED'), stale: sources.filter(s => s.health === 'STALE'), offline: sources.filter(s => s.health === 'OFFLINE') }
  }), [state, incidents, sources, permissions, role, can]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used inside AppProvider');
  return context;
}