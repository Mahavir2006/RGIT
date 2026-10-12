// Shared filter state for the command map.
//
// This is deliberately one reducer: the map, the statistics, the category counts and the
// incident list all read the same filtered set, so they cannot disagree. A single reducer is
// what makes "the list and the map always reflect the same dataset" true by construction
// rather than by remembering to update three components.
import { useCallback, useMemo, useReducer } from 'react';
import {
  CATEGORIES, CATEGORY_BY_ID, DEFAULT_FILTERS, SEVERITIES, STATUSES, SOURCES,
  EVIDENCE_STATES, DATA_MODES, TIME_WINDOWS, ACCESS_STATES, categoryForEventType
} from '../data/taxonomy.js';
import { normaliseSeverity, normaliseMode } from '../data/canonical.js';

const REFERENCE_NOW = new Date('2026-10-12T14:06:50+05:30').getTime();

function toggle(list, value) {
  return list.includes(value) ? list.filter(item => item !== value) : [...list, value];
}

export const filterReducer = (state, action) => {
  switch (action.type) {
    case 'toggleCategory': return { ...state, categories: toggle(state.categories, action.id) };
    case 'onlyCategory': return { ...state, categories: [action.id] };
    case 'setCategories': return { ...state, categories: action.value };
    case 'toggleSeverity': return { ...state, severities: toggle(state.severities, action.id) };
    case 'toggleStatus': return { ...state, statuses: toggle(state.statuses, action.id) };
    case 'toggleSource': return { ...state, sources: toggle(state.sources, action.id) };
    case 'toggleEvidence': return { ...state, evidence: toggle(state.evidence, action.id) };
    case 'toggleDataMode': return { ...state, dataModes: toggle(state.dataModes, action.id) };
    case 'setTimeWindow': return { ...state, timeWindow: action.value };
    case 'setCustomRange': return { ...state, customFrom: action.from, customTo: action.to };
    case 'setConfidence': return { ...state, confidenceMin: action.value };
    case 'setArea': return { ...state, area: action.value };
    case 'setQuery': return { ...state, query: action.value };
    case 'replace': return { ...state, ...action.value };
    case 'clearAll': return { ...DEFAULT_FILTERS, area: state.area, timeWindow: state.timeWindow };
    case 'resetFilters': return { ...DEFAULT_FILTERS, area: state.area, timeWindow: state.timeWindow };
    default: return state;
  }
};

export function useFilters(initial = DEFAULT_FILTERS) {
  const [filters, dispatch] = useReducer(filterReducer, initial);
  const actions = useMemo(() => ({
    toggleCategory: id => dispatch({ type: 'toggleCategory', id }),
    onlyCategory: id => dispatch({ type: 'onlyCategory', id }),
    setCategories: value => dispatch({ type: 'setCategories', value }),
    toggleSeverity: id => dispatch({ type: 'toggleSeverity', id }),
    toggleStatus: id => dispatch({ type: 'toggleStatus', id }),
    toggleSource: id => dispatch({ type: 'toggleSource', id }),
    toggleEvidence: id => dispatch({ type: 'toggleEvidence', id }),
    toggleDataMode: id => dispatch({ type: 'toggleDataMode', id }),
    setTimeWindow: value => dispatch({ type: 'setTimeWindow', value }),
    setCustomRange: (from, to) => dispatch({ type: 'setCustomRange', from, to }),
    setConfidence: value => dispatch({ type: 'setConfidence', value }),
    setArea: value => dispatch({ type: 'setArea', value }),
    setQuery: value => dispatch({ type: 'setQuery', value }),
    replace: value => dispatch({ type: 'replace', value }),
    clearAll: () => dispatch({ type: 'clearAll' })
  }), []);

  return [filters, actions];
}

export function activeFilterChips(filters) {
  const chips = [];
  // Category chips are only shown when the set is narrower than "everything".
  if (filters.categories.length < CATEGORIES.length) {
    for (const id of filters.categories) chips.push({ key: `cat:${id}`, label: CATEGORY_BY_ID[id]?.short ?? id, group: 'category', value: id });
  }
  if (filters.severities.length < SEVERITIES.length) {
    for (const id of filters.severities) chips.push({ key: `sev:${id}`, label: id.toLowerCase(), group: 'severity', value: id });
  }
  if (filters.statuses.length < STATUSES.length) {
    for (const id of filters.statuses) chips.push({ key: `st:${id}`, label: id.toLowerCase(), group: 'status', value: id });
  }
  if (filters.sources.length < SOURCES.length) {
    for (const id of filters.sources) chips.push({ key: `src:${id}`, label: id.replace(/_/g, ' '), group: 'source', value: id });
  }
  if (filters.evidence.length < EVIDENCE_STATES.length) {
    for (const id of filters.evidence) chips.push({ key: `ev:${id}`, label: id.toLowerCase(), group: 'evidence', value: id });
  }
  if (filters.dataModes.length < DATA_MODES.length) {
    for (const id of filters.dataModes) chips.push({ key: `mode:${id}`, label: id.toLowerCase(), group: 'mode', value: id });
  }
  if (filters.confidenceMin > 0) chips.push({ key: 'conf', label: `confidence ≥ ${filters.confidenceMin}`, group: 'confidence' });
  if (filters.query) chips.push({ key: 'q', label: `“${filters.query}”`, group: 'query' });
  return chips;
}

/** Remove a chip by removing its value from the matching group. */
export function removeChip(filters, chip) {
  if (chip.group === 'confidence') return { ...filters, confidenceMin: 0 };
  if (chip.group === 'query') return { ...filters, query: '' };
  return { ...filters, [chip.group]: filters[chip.group].filter(id => id !== chip.value) };
}

function windowBounds(filters) {
  if (filters.timeWindow === 'custom' && filters.customFrom && filters.customTo) {
    return { from: new Date(filters.customFrom).getTime(), to: new Date(filters.customTo).getTime() };
  }
  const definition = TIME_WINDOWS.find(item => item.id === filters.timeWindow) ?? TIME_WINDOWS[2];
  if (!definition.minutes) return { from: 0, to: Number.POSITIVE_INFINITY };
  const to = REFERENCE_NOW;
  return { from: to - definition.minutes * 60000, to };
}

export function evidenceStateOf(item) {
  // Evidence state is derived, never stored ad hoc: conflicting and stale evidence outranks
  // support, and an item with no usable evidence at all is explicitly insufficient.
  if (item.contradicting > 0 && item.supporting > 0) return 'CONFLICTING';
  if (item.stale) return 'STALE';
  if (!item.supporting && !item.contradicting) return 'INSUFFICIENT';
  return 'SUPPORTED';
}

/**
 * The single selector. Everything the map, the counts and the list render comes from here.
 *
 * @param items  normalised incidents: { id, category, severity, status, sourceTypes, areaName,
 *                    supporting, contradicting, stale, confidence, mode, lat, lon, updatedAt }
 */
export function selectFiltered(items, filters) {
  const { from, to } = windowBounds(filters);
  const needle = filters.query.trim().toLowerCase();
  const areaId = filters.area;

  const matched = [];
  const categoryCounts = Object.fromEntries(CATEGORIES.map(category => [category.id, 0]));

  for (const item of items) {
    if (!filters.categories.includes(item.category)) continue;
    if (!filters.severities.includes(normaliseSeverity(item.severity))) continue;
    if (!filters.statuses.includes(item.status)) continue;
    if (filters.sources.length && !item.sourceTypes?.some(source => filters.sources.includes(source))) continue;
    if (!filters.dataModes.includes(normaliseMode(item.mode))) continue;
    if (!filters.evidence.includes(evidenceStateOf(item))) continue;

    const observed = item.observedAt ? new Date(item.observedAt).getTime() : null;
    if (observed !== null && (observed < from || observed > to)) continue;

    if (typeof item.confidence === 'number' && item.confidence < filters.confidenceMin) continue;
    if (areaId !== 'All areas' && item.areaName !== areaId) continue;
    if (needle && !`${item.id} ${item.title} ${item.areaName} ${item.category}`.toLowerCase().includes(needle)) continue;

    matched.push(item);
    categoryCounts[item.category] = (categoryCounts[item.category] ?? 0) + 1;
  }

  return {
    items: matched,
    total: items.length,
    categoryCounts,
    windows: { from, to }
  };
}

/**
 * Emergency-access road states.
 *
 * A road is never marked clear because nothing reported it. It is only VERIFIED_PASSABLE when
 * a check actually confirmed it; otherwise absence of evidence produces UNKNOWN, which the UI
 * shows as a distinct, less alarming colour than a confirmed blockage.
 */
export function deriveAccessStates(roads, incidents) {
  return roads.map(road => {
    const affecting = incidents.filter(incident =>
      incident.impactsRoads?.includes(road.id) && incident.status !== 'RESOLVED');

    if (!affecting.length) {
      return {
        roadId: road.id, state: ACCESS_STATES.UNKNOWN,
        evidence: [], lastObservedAt: road.lastObservedAt ?? null,
        note: 'No usable observation for this segment inside the current window.'
      };
    }

    const observed = affecting.filter(incident => incident.accessEvidence === 'observed');
    const reported = affecting.filter(incident => incident.accessEvidence === 'reported');
    const modelled = affecting.filter(incident => incident.accessEvidence === 'modelled');

    let state = ACCESS_STATES.PREDICTED_RISK;
    let evidence = modelled;
    if (observed.length) { state = ACCESS_STATES.OBSERVED_BLOCKED; evidence = observed; }
    else if (reported.length) { state = ACCESS_STATES.REPORTED_BLOCKED; evidence = reported; }

    return {
      roadId: road.id,
      state,
      evidence: evidence.map(incident => ({ incidentId: incident.id, source: incident.accessSource, at: incident.accessObservedAt ?? incident.updatedAt })),
      lastObservedAt: evidence[0]?.accessObservedAt ?? null,
      note: `Driven by ${evidence.length} incident${evidence.length === 1 ? '' : 's'} on this segment.`
    };
  });
}

export function summarise(matched) {
  const bySeverity = {};
  for (const severity of SEVERITIES) bySeverity[severity] = matched.filter(item => normaliseSeverity(item.severity) === severity).length;
  return {
    count: matched.length,
    critical: bySeverity.CRITICAL || 0,
    high: bySeverity.HIGH || 0,
    bySeverity
  };
}