// Sentinel map — MapLibre GL with a keyless OpenStreetMap raster base.
//
// Why MapLibre rather than the earlier Three.js plane: operators need real geography,
// real pan/zoom, real clustering and real tile attribution. The raster source is the
// public OSM tile endpoint, which requires no credential; attribution is rendered in the
// map corner and the licence is recorded in THIRD_PARTY_NOTICES.md. A production
// deployment must move to an approved tile provider (PRD 15.1 is still TBD).
//
// If the raster fails the vector overlays still render, and Operations falls back to its
// synchronised list, so a tile outage never removes the incident picture.
import { useEffect, useRef, useMemo, useState } from 'react';
// MapLibre v6 is ESM-only and exports named bindings rather than a default.
import { Map as MapLibreMap, NavigationControl, AttributionControl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { ASSETS, AREAS, ASSET_DEPENDENCIES } from '@/data/geo.js';
import { useTheme } from '@/lib/theme.jsx';
import { categoryGlyphSvg, registerCategoryBadges } from '@/lib/categoryGlyphs.js';
import IncidentIndicators from './IncidentIndicators.jsx';
import IncidentLegend from './IncidentLegend.jsx';
import { buildThematicField } from '@/lib/hazardField.js';
import { CATEGORIES, CATEGORY_BY_ID, STATUS_COLOUR, EVIDENCE_STATE_COLOUR } from '@/data/taxonomy.js';

const CENTER = [72.872, 19.0625];

const SEVERITY_RANK = { CRITICAL: 0, HIGH: 1, MODERATE: 2, LOW: 3, INFO: 4 };

// The map is rendered from two callers: Overview passes store incidents, Operations passes the
// projected command-model items. Both shapes are accepted here so neither caller has to reshape
// its data purely to satisfy the map.
// Fitting an incident's own extent exactly lands around z17, which is building level: the
  // operator sees one block and loses all sense of where in the city they are. Framing a
// multiple of the extent keeps the affected area prominent while leaving context around it,
// and the zoom band stops a large incident from becoming a single dot or a small one from
// becoming an unrecognisable close-up.
const FOCUS_CONTEXT_FACTOR = 2.2;
const FOCUS_MIN_ZOOM = 12.5;
const FOCUS_MAX_ZOOM = 15.5;

const itemId = item => item.id ?? item.incident_id;
const itemArea = item => item.areaName ?? item.area_name;
const itemRadius = item => item.radiusM ?? item.impacted_radius_m ?? 400;

/**
 * The extent a viewer actually needs to see for an incident.
 *
 * Not just the reported impact radius: a location that is only accurate to 600m has to be framed
 * at 600m, or the map implies a precision the record does not have. The honest extent is the
 * larger of the two.
 */
function itemExtent(item) {
  const impact = itemRadius(item);
  const uncertainty = item.uncertaintyM ?? item.location_uncertainty_m ?? 0;
  return Math.max(impact, uncertainty, 250);
}

const METRES_PER_DEGREE_LAT = 111320;
const metresPerDegreeLon = lat => 111320 * Math.cos((lat * Math.PI) / 180);

/** Bounding box for a point and a radius, in degrees. */
function boundsFor(lat, lon, radiusMetres) {
  const latDelta = radiusMetres / METRES_PER_DEGREE_LAT;
  const lonDelta = radiusMetres / Math.max(1, metresPerDegreeLon(lat));
  return [[lon - lonDelta, lat - latDelta], [lon + lonDelta, lat + latDelta]];
}

function readTokens() {
  const styles = getComputedStyle(document.documentElement);
  const value = name => (styles.getPropertyValue(name).trim() || '#888888');
  return {
    accent: value('--accent'),
    healthy: value('--healthy'),
    degraded: value('--degraded'),
    stale: value('--stale'),
    critical: value('--critical'),
    info: value('--info'),
    fg: value('--fg'),
    fgMuted: value('--fg-muted'),
    border: value('--border'),
    surface: value('--surface')
  };
}

function hex(value) {
  return value.replace('#', '');
}

// Uncertainty rings are drawn as real polygons, so an area-level location is never
// presented as a precise pin.
function circlesFeatureCollection(points) {
  return {
    type: 'FeatureCollection',
    features: points.map(point => {
      const steps = 64;
      const ring = [];
      for (let step = 0; step <= steps; step++) {
        const angle = (step / steps) * Math.PI * 2;
        const dLat = (point.radiusKm / 110.574) * Math.sin(angle);
        const dLon = (point.radiusKm / (110.574 * Math.cos((point.lat * Math.PI) / 180))) * Math.cos(angle);
        ring.push([point.lon + dLon, point.lat + dLat]);
      }
      return {
        type: 'Feature',
        properties: { id: point.id, kind: point.kind, severity: point.severity ?? '', colour: point.colour },
        geometry: { type: 'Polygon', coordinates: [ring] }
      };
    })
  };
}

function pointsFeatureCollection(points) {
  return {
    type: 'FeatureCollection',
    features: points.map(point => ({
      type: 'Feature',
      properties: { id: point.id, kind: point.kind, severity: point.severity ?? '', colour: point.colour, label: point.label ?? '' },
      geometry: { type: 'Point', coordinates: [point.lon, point.lat] }
    }))
  };
}

export default function SentinelMap({
  incidents = [], candidates = [], assets = ASSETS, dependencies = ASSET_DEPENDENCIES,
  roads = [], accessStates = [],
  selection, onSelect, layers = {}, replay = 100, height = 520, showLegend = true, className = '',
  onBoundsChange,
  // `focus` drives the camera: { id, nonce }. Bumping nonce re-frames the same target, which is
  // what the "zoom to incident" control sends after the operator has panned away.
  focus = null,
  // Padding keeps the target clear of the incident rail, which sits beside the map and would
  // otherwise cover exactly the incident that was just clicked.
  fitPadding = { top: 24, bottom: 24, left: 24, right: 24 },
  fitOptions = { minZoom: FOCUS_MIN_ZOOM, maxZoom: FOCUS_MAX_ZOOM, duration: 700 },
  // 2D indicator overlay controls. Kept as plain props so the map stays presentational and
  // Operations owns the FX state.
  indicators = true, fxPaused = false, fxLowPerformance = false, fxHideUnselected = false
}) {
  const container = useRef(null);
  const mapRef = useRef(null);
  // The indicator overlay needs the live map instance to project coordinates. It is held in
  // state rather than read from the ref so the overlay mounts once the map exists.
  const [mapInstance, setMapInstance] = useState(null);
  const ready = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onBoundsRef = useRef(onBoundsChange);
  onBoundsRef.current = onBoundsChange;
  const { theme } = useTheme();
  const [tilesFailed, setTilesFailed] = useTilesFailed();

  // ---- GeoJSON derived from props -------------------------------------------------
  const incidentFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: incidents.map(incident => ({
      type: 'Feature',
      properties: {
        id: itemId(incident),
        kind: 'incident',
        severity: incident.severity,
        rank: SEVERITY_RANK[incident.severity] ?? 4,
        title: incident.title,
        area: itemArea(incident),
        status: incident.status,
        category: incident.category ?? 'reports',
        // The glyph id and the evidence state are carried on the feature so the symbology is
        // driven by data rather than by the map hard-coding a category list.
        glyph: incident.category ?? 'reports',
        evidence: incident.evidence ?? 'SUPPORTED',
        predicted: incident.isPredicted ? 1 : 0,
        stale: incident.stale ? 1 : 0
      },
      geometry: { type: 'Point', coordinates: [incident.lon, incident.lat] }
    }))
  }), [incidents]);

  const candidateFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: candidates.map(candidate => ({
      type: 'Feature',
      properties: { id: candidate.candidate_id, kind: 'candidate', severity: 'MODERATE', rank: 5, title: candidate.title, area: '', status: candidate.status },
      geometry: { type: 'Point', coordinates: [candidate.lon, candidate.lat] }
    }))
  }), [candidates]);

  const assetFeatures = useMemo(() => pointsFeatureCollection(assets.map(asset => ({
    id: asset.asset_id, kind: asset.type.toLowerCase(), lat: asset.lat, lon: asset.lon,
    label: asset.name, colour: asset.type
  }))), [assets]);

  const assetPolygons = useMemo(() => circlesFeatureCollection(assets.map(asset => ({
    id: asset.asset_id, kind: asset.type.toLowerCase(), lat: asset.lat, lon: asset.lon,
    radiusKm: 0.12, colour: asset.type
  }))), [assets]);

  const incidentCircles = useMemo(() => circlesFeatureCollection(incidents.map(incident => ({
    id: itemId(incident), kind: 'incident', lat: incident.lat, lon: incident.lon,
    radiusKm: itemRadius(incident) / 1000, severity: incident.severity,
    predicted: incident.isPredicted ? 1 : 0
  }))), [incidents]);

  const candidateCircles = useMemo(() => circlesFeatureCollection(candidates.map(candidate => ({
    id: candidate.candidate_id, kind: 'candidate', lat: candidate.lat, lon: candidate.lon, radiusKm: 0.9
  }))), [candidates]);

  const dependencyFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: dependencies.flatMap(edge => {
      const from = assets.find(asset => asset.asset_id === edge.from);
      const to = assets.find(asset => asset.asset_id === edge.to);
      if (!from || !to) return [];
      return [{
        type: 'Feature',
        properties: { semantics: edge.semantics, label: `${from.name} → ${to.name}` },
        geometry: { type: 'LineString', coordinates: [[from.lon, from.lat], [to.lon, to.lat]] }
      }];
    })
  }), [assets, dependencies]);

  // Thematic hazard geometry for every incident currently drawn. This is the "what does the
  // ground look like" layer; the badges say what kind of incident it is, this says what it did.
  const thematicFeatures = useMemo(() => buildThematicField(incidents), [incidents]);

  // Candidates are given an indicator too, but as an unreviewed cluster: dotted boundary, slow
  // pulse, no severity badge. An unreviewed candidate must never borrow a confirmed look.
  const indicatorItems = useMemo(() => [
    ...incidents,
    ...candidates.map(candidate => ({
      ...candidate,
      id: candidate.candidate_id,
      kind: 'candidate',
      areaName: candidate.areaName ?? 'Unassigned area',
      // A candidate is a cluster of reports, so its extent is the matching radius, stated.
      radiusM: 900,
      uncertaintyM: 900,
      locationPrecision: 'area'
    }))
  ], [incidents, candidates]);

  // Emergency-access overlay. Each segment carries its own state, and the state says how it is
  // known - observed, reported, modelled, or simply unobserved. An unobserved segment is drawn
  // muted rather than green, because silence is not evidence that a road is passable.
  const accessFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: accessStates.flatMap(entry => {
      const road = roads.find(item => item.id === entry.roadId);
      if (!road) return [];
      return [{
        type: 'Feature',
        properties: {
          id: road.id, kind: 'road', name: road.name,
          state: entry.state.id, label: entry.state.label, colour: entry.state.colour,
          note: entry.note, evidence: entry.state.evidence,
          observed: entry.lastObservedAt ? 1 : 0
        },
        geometry: { type: 'Point', coordinates: [road.lon, road.lat] }
      }];
    })
  }), [roads, accessStates]);

  // ---- Map creation ----------------------------------------------------------------
  useEffect(() => {
    const host = container.current;
    if (!host || mapRef.current) return undefined;

    const tokens = readTokens();
    let map;
    try {
      map = new MapLibreMap({
        container: host,
        center: CENTER,
        zoom: 11.2,
        minZoom: 9,
        maxZoom: 17,
        attributionControl: false,
        // Wheel zoom is what an operator reaches for on a dense map, so it stays on.
        scrollZoom: true,
        // A neutral light basemap; dark mode is achieved by muting the raster rather than
        // swapping in a second tile provider.
        style: {
          version: 8,
          sources: {
            osm: {
              type: 'raster',
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              tileSize: 256,
              maxzoom: 19,
              attribution: '© OpenStreetMap contributors'
            }
          },
          layers: [{ id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': 0.9 } }]
        }
      });
    } catch {
      setTilesFailed(true);
      return undefined;
    }

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(new AttributionControl({ compact: true }), 'bottom-right');

    const onError = event => {
      // Raster tile failures degrade to vector-only rather than blanking the map.
      if (event?.error && /tile|raster|source/i.test(String(event.error.message || event.error))) setTilesFailed(true);
    };
    map.on('error', onError);

    map.on('load', async () => {
      const add = (id, source, layer) => {
        map.addSource(id, source);
        map.addLayer(layer);
      };

      // Category badges must exist before any layer references them, or MapLibre errors on a
      // missing sprite and the whole incident layer fails to draw.
      await registerCategoryBadges(map, { rim: tokens.surface });

      add('deps', { type: 'geojson', data: dependencyFeatures }, {
        id: 'deps', type: 'line', source: 'deps',
        paint: {
          'line-width': 1.4,
          'line-dasharray': [2, 2],
          'line-color': ['match', ['get', 'semantics'],
            'OBSERVED', tokens.healthy,
            'HYPOTHESIS', tokens.degraded,
            'VALIDATED', tokens.accent,
            tokens.border]
        }
      });

      // Emergency access is added early so it sits beneath assets and incident markers. An
      // overlay that covers a marker is a missed incident, so draw order here is a safety
      // decision rather than a styling preference.
      add('access-roads', { type: 'geojson', data: accessFeatures }, {
        id: 'access-roads', type: 'circle', source: 'access-roads',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 4, 13, 11, 16, 18],
          'circle-color': ['get', 'colour'],
          // An unobserved segment is muted rather than drawn as reassuringly green.
          'circle-opacity': ['match', ['get', 'state'], 'UNKNOWN', 0.4, 0.85],
          'circle-stroke-width': 2,
          'circle-stroke-color': ['get', 'colour'],
          'circle-stroke-opacity': ['match', ['get', 'state'],
            'OBSERVED_BLOCKED', 1, 'REPORTED_BLOCKED', 0.9, 'PREDICTED_RISK', 0.4, 0.5]
        }
      });
      map.addLayer({
        id: 'access-roads-label', type: 'symbol', source: 'access-roads',
        minzoom: 11.5,
        layout: {
          'text-field': ['get', 'label'],
          'text-font': ['Open Sans Semibold'],
          'text-size': 10.5,
          'text-offset': [0, 1.7],
          'text-anchor': 'top'
        },
        paint: {
          'text-color': ['get', 'colour'],
          'text-halo-color': tokens.surface,
          'text-halo-width': 1.4
        }
      });

      addThematicLayers(map, thematicFeatures, tokens);

      add('asset-areas', { type: 'geojson', data: assetPolygons }, {
        id: 'asset-areas', type: 'fill', source: 'asset-areas',
        paint: { 'fill-color': tokens.border, 'fill-opacity': 0.1 }
      });

      add('assets', { type: 'geojson', data: assetFeatures }, {
        id: 'assets', type: 'circle', source: 'assets',
        paint: {
          'circle-radius': ['match', ['get', 'kind'], 'gauge', 5, 'hospital', 5, 'fire_station', 5, 3.2],
          'circle-color': ['match', ['get', 'kind'],
            'gauge', tokens.healthy,
            'hospital', tokens.healthy,
            'pump', tokens.accent,
            'drain', tokens.info,
            'underpass', tokens.degraded,
            tokens.border],
          'circle-opacity': 0.85,
          'circle-stroke-width': 1,
          'circle-stroke-color': tokens.surface
        }
      });

      // Candidate clusters render differently from reviewed incidents: dashed, neutral.
      add('candidate-areas', { type: 'geojson', data: candidateCircles }, {
        id: 'candidate-areas', type: 'fill', source: 'candidate-areas',
        paint: { 'fill-color': tokens.fgMuted, 'fill-opacity': 0.08 }
      });
      map.addLayer({
        id: 'candidate-areas-line', type: 'line', source: 'candidate-areas',
        paint: { 'line-color': tokens.fgMuted, 'line-width': 1.2, 'line-dasharray': [2, 2], 'line-opacity': 0.7 }
      });

      add('incident-areas', { type: 'geojson', data: incidentCircles }, {
        id: 'incident-areas', type: 'fill', source: 'incident-areas',
        paint: {
          'fill-color': ['match', ['get', 'severity'], 'CRITICAL', tokens.critical, 'HIGH', tokens.degraded, 'MODERATE', tokens.stale, tokens.info],
          'fill-opacity': 0.1
        }
      });
      map.addLayer({
        id: 'incident-areas-line', type: 'line', source: 'incident-areas',
        paint: {
          'line-color': ['match', ['get', 'severity'], 'CRITICAL', tokens.critical, 'HIGH', tokens.degraded, 'MODERATE', tokens.stale, tokens.info],
          'line-width': 1.2, 'line-opacity': 0.5
        }
      });

      // Incident markers cluster; the cluster count is always shown.
      add('incidents', { type: 'geojson', data: incidentFeatures, cluster: true, clusterMaxZoom: 13, clusterRadius: 44 }, {
        id: 'incident-clusters', type: 'circle', source: 'incidents',
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': tokens.accent,
          'circle-opacity': 0.16,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': tokens.accent,
          'circle-stroke-opacity': 0.5,
          'circle-radius': ['step', ['get', 'point_count'], 16, 3, 21, 8, 27]
        }
      });
      map.addLayer({
        id: 'incident-cluster-count', type: 'symbol', source: 'incidents',
        filter: ['has', 'point_count'],
        layout: {
          'text-field': ['get', 'point_count_abbreviated'],
          'text-font': ['Open Sans Semibold'],
          'text-size': 12
        },
        paint: { 'text-color': tokens.accent }
      });
      // Symbology stack, drawn bottom-up so each filter dimension gets its own readable
      // channel instead of one colour trying to carry category, severity, status and
      // evidence at once:
      //   severity halo -> category badge -> evidence ring -> status ring -> label
      // Each filter the panel exposes therefore has a visible consequence on the map.
      map.addLayer({
        id: 'incident-points', type: 'circle', source: 'incidents',
        filter: ['!', ['has', 'point_count']],
        paint: {
          // Halo size carries severity; it is a ring, not a fill, so the badge stays legible.
          'circle-radius': ['match', ['get', 'severity'], 'CRITICAL', 19, 'HIGH', 17, 'MODERATE', 15, 13],
          'circle-color': ['match', ['get', 'severity'], 'CRITICAL', tokens.critical, 'HIGH', tokens.degraded, 'MODERATE', tokens.stale, tokens.info],
          'circle-opacity': ['match', ['get', 'severity'], 'CRITICAL', 0.22, 0.14],
          'circle-stroke-width': ['match', ['get', 'severity'], 'CRITICAL', 2.5, 1.5],
          'circle-stroke-color': ['match', ['get', 'severity'], 'CRITICAL', tokens.critical, 'HIGH', tokens.degraded, 'MODERATE', tokens.stale, tokens.info],
          'circle-stroke-opacity': 0.95
        }
      });

      // A predicted cascade is drawn dashed and hollow. A modelled consequence that looks like
      // an observation is the single most dangerous thing this map could do.
      map.addLayer({
        id: 'incident-predicted-ring', type: 'circle', source: 'incidents',
        filter: ['all', ['!', ['has', 'point_count']], ['==', ['get', 'predicted'], 1]],
        paint: {
          'circle-radius': 22,
          'circle-color': 'transparent',
          'circle-stroke-width': 2,
          'circle-stroke-color': CATEGORY_BY_ID.cascade?.colour ?? tokens.accent,
          'circle-stroke-opacity': 0.9,
          'circle-stroke-dasharray': [2.5, 2.5]
        }
      });

      // The category badge is the primary mark. Shape plus colour together, so the map reads
      // correctly for someone who cannot separate the category hues.
      map.addLayer({
        id: 'incident-glyph', type: 'symbol', source: 'incidents',
        filter: ['!', ['has', 'point_count']],
        layout: {
          'icon-image': ['concat', 'cat-', ['get', 'glyph']],
          // Scale with severity so critical incidents read as larger, not just redder.
          'icon-size': ['match', ['get', 'severity'], 'CRITICAL', 0.62, 'HIGH', 0.55, 0.48],
          'icon-allow-overlap': false,
          'icon-ignore-placement': false,
          'icon-offset': [0, 0]
        },
        paint: { 'icon-opacity': 0.96 }
      });

      // Evidence state is drawn as a ring colour, because evidence quality is orthogonal to
      // what the incident is: a conflicting flood report and a confirmed fire both need it.
      map.addLayer({
        id: 'incident-evidence-ring', type: 'circle', source: 'incidents',
        filter: ['all', ['!', ['has', 'point_count']], ['!=', ['get', 'evidence'], 'SUPPORTED']],
        paint: {
          'circle-radius': 25,
          'circle-color': 'transparent',
          'circle-stroke-width': 2,
          'circle-stroke-color': [
            'match', ['get', 'evidence'],
            'CONFLICTING', EVIDENCE_STATE_COLOUR.CONFLICTING,
            'STALE', EVIDENCE_STATE_COLOUR.STALE,
            'INSUFFICIENT', EVIDENCE_STATE_COLOUR.INSUFFICIENT,
            tokens.fgSubtle
          ],
          'circle-stroke-opacity': 0.95
        }
      });

      // Command status is a small arc at the top of the marker rather than another full ring,
      // so four rings stacked on one point do not become an unreadable target.
      map.addLayer({
        id: 'incident-status-ring', type: 'circle', source: 'incidents',
        filter: ['all', ['!', ['has', 'point_count']], ['!=', ['get', 'status'], 'CONFIRMED']],
        paint: {
          'circle-radius': 15.5,
          'circle-color': 'transparent',
          'circle-stroke-width': 3,
          'circle-stroke-color': ['match', ['get', 'status'],
            'ESCALATED', STATUS_COLOUR.ESCALATED,
            'RESOLVED', STATUS_COLOUR.RESOLVED,
            'NEW', STATUS_COLOUR.NEW,
            'INVESTIGATING', STATUS_COLOUR.INVESTIGATING,
            tokens.fgSubtle],
          'circle-stroke-opacity': 0.9,
          'circle-stroke-dasharray': [4, 4]
        }
      });
      map.addLayer({
        id: 'incident-label', type: 'symbol', source: 'incidents',
        filter: ['!', ['has', 'point_count']],
        layout: {
          'text-field': ['get', 'id'],
          'text-font': ['Open Sans Semibold'],
          'text-size': 11,
          'text-offset': [0, 1.6],
          'text-anchor': 'top'
        },
        paint: { 'text-color': tokens.fg, 'text-halo-color': tokens.surface, 'text-halo-width': 1.4 }
      });

      // Selection ring sits above everything so the active object is unmistakable.
      add('selection', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: incidents.filter(item => itemId(item) === selection).map(item => ({
          type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [item.lon, item.lat] }
        })) }
      }, {
        id: 'selection', type: 'circle', source: 'selection',
        paint: {
          'circle-radius': 15,
          'circle-color': 'transparent',
          'circle-stroke-width': 2,
          'circle-stroke-color': tokens.accent,
          'circle-stroke-opacity': 0.9
        }
      });

      applyLayers(map, layers, tokens);

      map.on('click', 'incident-points', event => {
        const feature = event.features?.[0];
        if (feature) onSelectRef.current?.({ kind: 'incident', id: feature.properties.id });
      });
      // The badge is the click target an operator actually aims at.
      map.on('click', 'incident-glyph', event => {
        const feature = event.features?.[0];
        if (feature) onSelectRef.current?.({ kind: 'incident', id: feature.properties.id });
      });
      map.on('click', 'incident-clusters', event => {
        const feature = event.features?.[0];
        if (!feature) return;
        map.getSource('incidents')?.getClusterExpansionZoom(feature.properties.cluster_id)
          ?.then(zoom => map.easeTo({ center: feature.geometry.coordinates, zoom, duration: 400 }))
          .catch(() => { });
      });
      map.on('click', 'assets', event => {
        const feature = event.features?.[0];
        if (feature) onSelectRef.current?.({ kind: 'asset', id: feature.properties.id, title: feature.properties.label });
      });
      map.on('click', 'deps', event => {
        const feature = event.features?.[0];
        if (feature) onSelectRef.current?.({ kind: 'dependency', title: feature.properties.label, semantics: feature.properties.semantics });
      });
      map.on('click', 'access-roads', event => {
        const feature = event.features?.[0];
        if (!feature) return;
        onSelectRef.current?.({
          kind: 'road', id: feature.properties.id, title: feature.properties.name,
          state: feature.properties.state, note: feature.properties.note,
          evidence: feature.properties.evidence,
          // A road is not an incident, so hand over the coordinates for the camera directly.
          lon: feature.geometry.coordinates[0], lat: feature.geometry.coordinates[1],
          radiusM: 420
        });
      });
      for (const layer of ['incident-points', 'incident-glyph', 'incident-clusters', 'assets', 'deps', 'access-roads']) {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      }

      // Report the viewport so the caller can count what is actually on screen.
      const reportBounds = () => {
        const box = map.getBounds();
        onBoundsRef.current?.({
          west: box.getWest(), east: box.getEast(),
          south: box.getSouth(), north: box.getNorth()
        });
      };
      map.on('moveend', reportBounds);
      reportBounds();

      ready.current = true;
    });

    mapRef.current = map;
    setMapInstance(map);
    // The filter panel opening and closing changes this container's height. MapLibre caches
    // its canvas size, so without an explicit resize the map keeps a stale size and stops
    // responding correctly to wheel zoom and drag panning.
    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(host);
    return () => {
      ready.current = false;
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      setMapInstance(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Data updates ----------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.getSource('incidents')?.setData(incidentFeatures);
  }, [incidentFeatures]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.getSource('selection')?.setData({
      type: 'FeatureCollection',
      features: incidents.filter(item => itemId(item) === selection).map(item => ({
        type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [item.lon, item.lat] }
      }))
    });
    // The camera is deliberately NOT moved here. This effect also runs whenever `incidents`
    // changes, which happens on every filter change - easing on each of those would yank the
    // camera back while the operator was trying to look somewhere. Framing is driven by
    // `focus` alone, below.
  }, [selection, incidents]);

  // Frame the focused incident at a zoom that actually shows it.
  //
  // Re-centring alone leaves the camera at city zoom, so a 300m flood reads as one dot in a
  // wide view. Fitting the box the incident actually occupies - impact radius or stated
  // uncertainty, whichever is larger - puts the operator at the scale where the hazard ribbons
  // and asset labels are legible.
  const focusRef = useRef(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current || !focus?.id) return;
    const signature = `${focus.id}:${focus.nonce ?? 0}`;
    // Refit only on a genuinely new request, so re-renders do not restart the animation.
    if (focusRef.current === signature) return;
    focusRef.current = signature;

    // A focus may carry explicit coordinates (a road segment or asset is not an incident and
    // will not be found in the incident list), so resolve either way.
    const target = incidents.find(item => itemId(item) === focus.id);
    const lat = focus.lat ?? target?.lat;
    const lon = focus.lon ?? target?.lon;
    if (typeof lat !== 'number' || typeof lon !== 'number') return;
    const radius = focus.radiusM ?? (target ? itemExtent(target) : 300);
    map.fitBounds(boundsFor(lat, lon, radius * FOCUS_CONTEXT_FACTOR), {
      padding: fitPadding,
      minZoom: fitOptions.minZoom,
      maxZoom: focus.maxZoom ?? fitOptions.maxZoom,
      duration: fitOptions.duration
    });
  }, [focus, incidents, fitPadding, fitOptions]);

  // Opening the map should frame what is actually on it rather than a hard-coded centre, so a
  // filtered-down view is not left looking at an empty part of the city.
  const framedRef = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    if (framedRef.current || incidents.length === 0) return;
    framedRef.current = true;
    if (incidents.length === 1) {
      const only = incidents[0];
      map.fitBounds(boundsFor(only.lat, only.lon, itemExtent(only) * FOCUS_CONTEXT_FACTOR), {
        padding: fitPadding, minZoom: fitOptions.minZoom, maxZoom: fitOptions.maxZoom, duration: 0
      });
      return;
    }
    let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
    for (const item of incidents) {
      const [[lo, la], [hi, lb]] = boundsFor(item.lat, item.lon, itemExtent(item));
      west = Math.min(west, lo); south = Math.min(south, la);
      east = Math.max(east, hi); north = Math.max(north, lb);
    }
    map.fitBounds([[west, south], [east, north]], {
      padding: fitPadding, minZoom: 9, maxZoom: 13.5, duration: 0
    });
  }, [incidents, fitPadding, fitOptions]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.getSource('deps')?.setData(dependencyFeatures);
    map.getSource('assets')?.setData(assetFeatures);
    map.getSource('access-roads')?.setData(accessFeatures);
  }, [dependencyFeatures, assetFeatures, accessFeatures]);

  // The hazard field follows the filtered set, so filtering by category also decides which
  // ground depictions remain on the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.getSource('thematic')?.setData(thematicFeatures);
  }, [thematicFeatures]);

  // ---- Layer toggles ---------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    applyLayers(map, layers, readTokens());
  }, [layers]);

  // Rainfall overlay opacity follows the replay scrub.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    const opacity = Math.max(0, Math.min(0.45, ((replay - 25) / 100) * 0.5));
    if (map.getLayer('rain')) map.setPaintProperty('rain', 'circle-opacity', opacity);
  }, [replay]);

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    host.style.filter = theme === 'dark' ? 'invert(0.92) hue-rotate(180deg) brightness(0.94) contrast(0.92)' : 'none';
  }, [theme]);

  return (
    <div className={`relative overflow-hidden ${className}`} style={{ height }}>
      <div ref={container} className="h-full w-full" />

      {/* The indicator overlay sits above the canvas but below the controls, so a click that
          misses an indicator still reaches the map for panning. */}
      {indicators && mapInstance && (
        <IncidentIndicators
          map={mapInstance}
          incidents={indicatorItems}
          selection={selection}
          onSelect={hit => onSelectRef.current?.({ kind: 'incident', id: hit.id, item: hit })}
          paused={fxPaused}
          lowPerformance={fxLowPerformance}
          hideUnselected={fxHideUnselected}
        />
      )}
      {tilesFailed && (
        <div className="absolute left-3 top-3 max-w-xs rounded-[8px] border border-degraded/30 bg-degraded-soft px-3 py-2 text-[12px] text-degraded">
          Base map tiles are unavailable. Vector overlays are still drawn, and the incident list carries the same
          information. Check the OSM tile provider or switch to an approved tile source.
        </div>
      )}
      {/* The animated legend replaces the old static swatch list. It is generated from the
          same registry the map uses, so an entry can never show a treatment the map lacks. */}
      {showLegend && (
        <IncidentLegend incidents={indicatorItems} paused={fxPaused} />
      )}
    </div>
  );
}

/**
 * Thematic hazard layers.
 *
 * Each theme gets a treatment that matches what is physically happening, rather than one generic
 * blob per incident. Standing water is drawn as filled ribbons along the carriageway; congestion
 * and access corridors as directional ribbons; heat, haze, crowd and rain as blurred fields,
 * because those genuinely are smooth fields; a cascade as an unfilled chain.
 *
 * Detail is gated by zoom. Below z12 the operator gets the coarse extent - enough to see where
 * the problem is. Between z12 and z13.5 the individual street ribbons and cells resolve. Above
 * z13.5 the fine ribbons appear. Each gate is a minzoom on the layer, so MapLibre does the
 * culling rather than shipping every feature at every zoom.
 */
function addThematicLayers(map, data, tokens) {
  map.addSource('thematic', { type: 'geojson', data });

  // --- Standing water: the flagship case -----------------------------------------
  // Two passes so the ribbons read as depth. Shallow water is a lighter wash, deep water
  // darker, and the ribbon edges carry a thin line so a flooded street stays a street.
  for (const detail of [0, 1]) {
    map.addLayer({
      id: `thematic-water-${detail}`, type: 'fill', source: 'thematic',
      filter: ['all', ['==', ['get', 'theme'], 'water'], ['==', ['get', 'detail'], detail]],
      minzoom: detail ? 13.5 : 0,
      paint: {
        'fill-color': [
          'interpolate', ['linear'], ['get', 'depth'],
          0, '#7dd3fc',
          0.35, '#38bdf8',
          0.7, '#0284c7',
          1, '#075985'
        ],
        'fill-opacity': ['interpolate', ['linear'], ['get', 'depth'], 0, 0.24, 1, 0.62]
      }
    });
    map.addLayer({
      id: `thematic-water-line-${detail}`, type: 'line', source: 'thematic',
      filter: ['all', ['==', ['get', 'theme'], 'water'], ['==', ['get', 'detail'], detail]],
      minzoom: detail ? 13.5 : 11,
      paint: {
        'line-color': '#0ea5e9',
        'line-width': detail ? 1.4 : 1,
        'line-opacity': 0.7
      }
    });
  }

  // Soft halo so a flooded area reads as a wet zone at city zoom, not just thin ribbons.
  map.addLayer({
    id: 'thematic-water-halo', type: 'circle', source: 'thematic',
    filter: ['==', ['get', 'theme'], 'water-halo'],
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'spreadM'], 100, 400, 900, 1100],
      'circle-color': '#38bdf8',
      'circle-opacity': 0.1,
      'circle-blur': 0.9
    }
  });

  // --- Ponding at named assets ---------------------------------------------------
  map.addLayer({
    id: 'thematic-ponding', type: 'circle', source: 'thematic',
    filter: ['==', ['get', 'theme'], 'ponding'],
    minzoom: 11,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 90, 15, 200],
      'circle-color': '#22d3ee',
      'circle-opacity': 0.3,
      'circle-stroke-width': 1.5,
      'circle-stroke-color': '#0e7490',
      'circle-stroke-opacity': 0.6,
      'circle-blur': 0.35
    }
  });

  // --- Ribbon themes: congestion, corridor, blockage, damage, disruption ----------
  const ribbons = [
    ['congestion', '#f59e0b', 12, 0.45],
    ['corridor', '#ef4444', 12, 0.4],
    ['blockage', '#f97316', 12, 0.42],
    ['damage', '#a3a3a3', 12, 0.38],
    ['disruption', '#22d3ee', 12, 0.38]
  ];
  for (const [theme, colour, minzoom, opacity] of ribbons) {
    map.addLayer({
      id: `thematic-${theme}`, type: 'fill', source: 'thematic',
      filter: ['==', ['get', 'theme'], theme],
      minzoom,
      paint: { 'fill-color': colour, 'fill-opacity': opacity }
    });
    map.addLayer({
      id: `thematic-${theme}-line`, type: 'line', source: 'thematic',
      filter: ['==', ['get', 'theme'], theme],
      minzoom: minzoom + 1,
      paint: {
        'line-color': colour,
        'line-width': 1.6,
        'line-opacity': 0.8,
        'line-dasharray': theme === 'corridor' ? [3, 2] : [1, 0]
      }
    });
  }

  // --- Blurred scalar fields -----------------------------------------------------
  // Radius is driven by the generator's own spread so a cell is drawn at the size it was
  // modelled, rather than at a fixed pixel size that would grow with zoom and overlap itself.
  const fields = [
    ['heat', '#fb7185', 12, 0.5],
    ['haze', '#a78bfa', 0, 0.3],
    ['crowd', '#c084fc', 11.5, 0.45],
    ['rain', '#60a5fa', 0, 0.26],
    ['outage', '#facc15', 11.5, 0.34],
    ['signal', '#e879f9', 12.5, 0.34]
  ];
  for (const [theme, colour, minzoom, opacity] of fields) {
    map.addLayer({
      id: `thematic-${theme}`, type: 'circle', source: 'thematic',
      filter: ['==', ['get', 'theme'], theme],
      minzoom,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'spreadM'], 80, 160, 900, 620],
        'circle-color': colour,
        'circle-opacity': ['interpolate', ['linear'], ['get', 'intensity'], 0.2, opacity * 0.4, 1, opacity],
        'circle-blur': 0.85
      }
    });
  }

  // --- Cascade chain: unfilled, because nothing here has been observed ------------
  map.addLayer({
    id: 'thematic-chain-link', type: 'line', source: 'thematic',
    filter: ['==', ['get', 'theme'], 'chain-link'],
    paint: {
      'line-color': '#f43f5e',
      'line-width': 2,
      'line-opacity': 0.85,
      'line-dasharray': [2.5, 2]
    }
  });
  map.addLayer({
    id: 'thematic-chain', type: 'circle', source: 'thematic',
    filter: ['==', ['get', 'theme'], 'chain'],
    paint: {
      'circle-radius': 6,
      'circle-color': 'transparent',
      'circle-stroke-width': 2,
      'circle-stroke-color': '#f43f5e',
      'circle-stroke-opacity': 0.95
    }
  });
  map.addLayer({
    id: 'thematic-chain-cause', type: 'circle', source: 'thematic',
    filter: ['all', ['==', ['get', 'theme'], 'chain'], ['==', ['get', 'step'], 'cause']],
    paint: { 'circle-radius': 4, 'circle-color': '#fb7185', 'circle-opacity': 0.95 }
  });
  map.addLayer({
    id: 'thematic-chain-effect', type: 'circle', source: 'thematic',
    filter: ['all', ['==', ['get', 'theme'], 'chain'], ['==', ['get', 'step'], 'effect']],
    paint: { 'circle-radius': 4, 'circle-color': '#f43f5e', 'circle-opacity': 0.95 }
  });

  // --- A silent sensor: a marker at the sensor, never an area --------------------
  map.addLayer({
    id: 'thematic-dead-sensor', type: 'circle', source: 'thematic',
    filter: ['==', ['get', 'theme'], 'dead-sensor'],
    minzoom: 10,
    paint: {
      'circle-radius': 7,
      'circle-color': 'transparent',
      'circle-stroke-width': 1.6,
      'circle-stroke-color': tokens.degraded,
      'circle-stroke-opacity': 0.9,
      'circle-stroke-dasharray': [2, 2]
    }
  });

  // Labels for the named assets inside a ponding or outage field, so the blob is answerable.
  map.addLayer({
    id: 'thematic-asset-label', type: 'symbol', source: 'thematic',
    filter: ['all', ['in', ['get', 'theme'], ['literal', ['ponding', 'dead-sensor', 'outage']]]],
    minzoom: 13,
    layout: {
      'text-field': ['get', 'asset'],
      'text-font': ['Open Sans Semibold'],
      'text-size': 10,
      'text-offset': [0, 1.6],
      'text-anchor': 'top'
    },
    paint: {
      'text-color': tokens.fg,
      'text-halo-color': tokens.surface,
      'text-halo-width': 1.3
    }
  });
}

const THEME_LAYER_IDS = [
  'thematic-water-0', 'thematic-water-1', 'thematic-water-line-0', 'thematic-water-line-1',
  'thematic-water-halo', 'thematic-ponding', 'thematic-heat', 'thematic-haze',
  'thematic-crowd', 'thematic-rain', 'thematic-outage', 'thematic-signal',
  'thematic-congestion', 'thematic-congestion-line', 'thematic-corridor', 'thematic-corridor-line',
  'thematic-blockage', 'thematic-blockage-line', 'thematic-damage', 'thematic-damage-line',
  'thematic-disruption', 'thematic-disruption-line', 'thematic-chain', 'thematic-chain-link',
  'thematic-chain-cause', 'thematic-chain-effect', 'thematic-dead-sensor', 'thematic-asset-label'
];

function applyLayers(map, layers, tokens) {
  const visibility = on => (on ? 'visible' : 'none');
  const pairs = [
    ['incidents', ['incident-points', 'incident-clusters', 'incident-cluster-count', 'incident-label']],
    ['impactZones', ['incident-areas', 'incident-areas-line']],
    ['candidates', ['candidate-areas', 'candidate-areas-line']],
    ['assets', ['assets', 'asset-areas']],
    ['dependencies', ['deps']],
    ['emergencyAccess', ['access-roads', 'access-roads-label']],
    ['rainfall', ['rain']]
  ];
  for (const [key, ids] of pairs) {
    if (layers[key] === undefined) continue;
    for (const id of ids) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visibility(layers[key]));
    }
  }
  // The hazard field is many layers rather than one, so it is toggled as a set.
  if (layers.hazard !== undefined) {
    for (const id of THEME_LAYER_IDS) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visibility(layers.hazard));
    }
  }
  // Rain overlay is a translucent wash drawn over the incidents.
  if (map.getLayer('rain') && layers.rainfall !== false) {
    if (!map.getSource('rain')) {
      map.addSource('rain', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: AREAS.map(area => ({
          type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [area.lon, area.lat] }
        })) }
      });
      map.addLayer({
        id: 'rain', type: 'circle', source: 'rain',
        paint: {
          // Overlapping large circles approximate an intensity wash without a raster.
          'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 9, 9000, 13, 26000],
          'circle-color': tokens.info,
          'circle-opacity': 0,
          'circle-blur': 1
        }
      });
    }
    map.setLayoutProperty('rain', 'visibility', visibility(layers.rainfall));
  }
}

// Minimal state hook: true once a raster tile error has been observed.
function useTilesFailed() {
  const [failed, setFailed] = useState(false);
  return [failed, setFailed];
}
