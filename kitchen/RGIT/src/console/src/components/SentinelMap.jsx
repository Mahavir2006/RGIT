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

const CENTER = [72.872, 19.0625];

const SEVERITY_RANK = { CRITICAL: 0, HIGH: 1, MODERATE: 2, LOW: 3, INFO: 4 };

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
  selection, onSelect, layers = {}, replay = 100, height = 520, showLegend = true, className = ''
}) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const ready = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const { theme } = useTheme();
  const [tilesFailed, setTilesFailed] = useTilesFailed();

  // ---- GeoJSON derived from props -------------------------------------------------
  const incidentFeatures = useMemo(() => ({
    type: 'FeatureCollection',
    features: incidents.map(incident => ({
      type: 'Feature',
      properties: {
        id: incident.incident_id,
        kind: 'incident',
        severity: incident.severity,
        rank: SEVERITY_RANK[incident.severity] ?? 4,
        title: incident.title,
        area: incident.area_name,
        status: incident.status
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
    id: incident.incident_id, kind: 'incident', lat: incident.lat, lon: incident.lon,
    radiusKm: (incident.impacted_radius_m || 400) / 1000, severity: incident.severity
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

    map.on('load', () => {
      const add = (id, source, layer) => {
        map.addSource(id, source);
        map.addLayer(layer);
      };

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
      map.addLayer({
        id: 'incident-points', type: 'circle', source: 'incidents',
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-radius': ['match', ['get', 'severity'], 'CRITICAL', 9, 'HIGH', 7.5, 6.5],
          'circle-color': ['match', ['get', 'severity'], 'CRITICAL', tokens.critical, 'HIGH', tokens.degraded, 'MODERATE', tokens.stale, tokens.info],
          'circle-stroke-width': 2,
          'circle-stroke-color': tokens.surface
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
        data: { type: 'FeatureCollection', features: incidents.filter(item => item.incident_id === selection).map(item => ({
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
      for (const layer of ['incident-points', 'incident-clusters', 'assets', 'deps']) {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      }

      ready.current = true;
    });

    mapRef.current = map;
    return () => {
      ready.current = false;
      map.remove();
      mapRef.current = null;
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
      features: incidents.filter(item => item.incident_id === selection).map(item => ({
        type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [item.lon, item.lat] }
      }))
    });
    if (selection) {
      const target = incidents.find(item => item.incident_id === selection);
      if (target) map.easeTo({ center: [target.lon, target.lat], duration: 500 });
    }
  }, [selection, incidents]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready.current) return;
    map.getSource('deps')?.setData(dependencyFeatures);
    map.getSource('assets')?.setData(assetFeatures);
  }, [dependencyFeatures, assetFeatures]);

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
      {tilesFailed && (
        <div className="absolute left-3 top-3 max-w-xs rounded-[8px] border border-degraded/30 bg-degraded-soft px-3 py-2 text-[12px] text-degraded">
          Base map tiles are unavailable. Vector overlays are still drawn, and the incident list carries the same
          information. Check the OSM tile provider or switch to an approved tile source.
        </div>
      )}
      {showLegend && (
        <div className="pointer-events-none absolute bottom-3 left-3 rounded-[8px] border border-border bg-surface/95 px-3 py-2">
          <div className="mb-1.5 text-[12px] font-medium text-fg">Legend</div>
          {[
            ['CRITICAL', 'var(--critical)'], ['HIGH', 'var(--degraded)'],
            ['MODERATE', 'var(--stale)'], ['LOW', 'var(--info)']
          ].map(([label, colour]) => (
            <div key={label} className="flex items-center gap-2 py-0.5 text-[12px] text-fg-muted">
              <span className="size-1.5 rounded-full" style={{ background: colour }} />
              {label.charAt(0) + label.slice(1).toLowerCase()}
            </div>
          ))}
          <div className="mt-1 flex items-center gap-2 py-0.5 text-[12px] text-fg-muted">
            <span className="size-2.5 rounded-full border border-dashed border-fg-subtle" />
            Location uncertainty
          </div>
          <div className="flex items-center gap-2 py-0.5 text-[12px] text-fg-muted">
            <span className="size-2.5 rounded-full border border-dashed border-fg-muted" />
            Candidate cluster
          </div>
        </div>
      )}
    </div>
  );
}

function applyLayers(map, layers, tokens) {
  const visibility = on => (on ? 'visible' : 'none');
  const pairs = [
    ['incidents', ['incident-points', 'incident-clusters', 'incident-cluster-count', 'incident-label']],
    ['impactZones', ['incident-areas', 'incident-areas-line']],
    ['candidates', ['candidate-areas', 'candidate-areas-line']],
    ['assets', ['assets', 'asset-areas']],
    ['dependencies', ['deps']],
    ['rainfall', ['rain']]
  ];
  for (const [key, ids] of pairs) {
    if (layers[key] === undefined) continue;
    for (const id of ids) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visibility(layers[key]));
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