// Mumbai operating area and infrastructure seed geometry.
//
// Coordinates are real locality centroids for the named Mumbai areas. The road, drainage and
// facility segments below are AUTHORED schematic geometry for the prototype - they are not
// extracted from OpenStreetMap, and nothing here should be treated as a surveyed network.
// A real deployment replaces this file with an Overpass extraction carrying ODbL attribution.

export const CITY = { name: 'Mumbai', country: 'India', timezone: 'Asia/Kolkata', utcOffset: '+05:30' };

export const SCENARIO_CLOCK = {
  name: 'Monsoon waterlogging · Andheri East',
  startedAt: '2026-10-12T13:30:00+05:30',
  observedAt: '2026-10-12T14:05:00+05:30'
};

export const AREAS = [
  { area_id: 'AR-ANDHERI-EAST', name: 'Andheri East', lat: 19.1197, lon: 72.8464 },
  { area_id: 'AR-POWAI', name: 'Powai', lat: 19.1176, lon: 72.906 },
  { area_id: 'AR-DADAR', name: 'Dadar', lat: 19.0178, lon: 72.8478 },
  { area_id: 'AR-KURLA', name: 'Kurla', lat: 19.0726, lon: 72.8846 },
  { area_id: 'AR-BANDRA', name: 'Bandra', lat: 19.0596, lon: 72.8295 },
  { area_id: 'AR-VILE-PARLE', name: 'Vile Parle', lat: 19.099, lon: 72.837 },
  { area_id: 'AR-CHEMBUR', name: 'Chembur', lat: 19.0595, lon: 72.8975 }
];

// Assets mirror the (:Asset) label: asset_id, type, geometry, source, freshness.
export const ASSETS = [
  { asset_id: 'AST-ANDH-UNDERPASS', type: 'UNDERPASS', name: 'Andheri station underpass', lat: 19.1197, lon: 72.8464, source: 'authored_seed', freshness: '2026-10-12T13:40:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-ANDH-DRAIN-04', type: 'DRAIN', name: 'Andheri drain DM-04', lat: 19.1201, lon: 72.8471, source: 'authored_seed', freshness: '2026-10-12T13:52:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-ANDH-GAUGE-04', type: 'GAUGE', name: 'Andheri water gauge WG-04', lat: 19.1204, lon: 72.8469, source: 'authored_seed', freshness: '2026-10-12T13:52:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-ANDH-GAUGE-09', type: 'GAUGE', name: 'Sahar water gauge WG-09', lat: 19.1132, lon: 72.8541, source: 'authored_seed', freshness: '2026-10-12T13:49:00+05:30', criticality: 'MEDIUM' },
  { asset_id: 'AST-ANDH-GAUGE-07', type: 'GAUGE', name: 'Marol water gauge WG-07', lat: 19.1261, lon: 72.8398, source: 'authored_seed', freshness: '2026-10-12T12:58:00+05:30', criticality: 'MEDIUM' },
  { asset_id: 'AST-ANDH-ROAD-SEG-12', type: 'ROAD_SEGMENT', name: 'Andheri East road segment S-12', lat: 19.1188, lon: 72.8452, source: 'authored_seed', freshness: '2026-10-12T13:35:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-ANDH-ROAD-SEG-13', type: 'ROAD_SEGMENT', name: 'Andheri East road segment S-13', lat: 19.1215, lon: 72.8487, source: 'authored_seed', freshness: '2026-10-12T13:35:00+05:30', criticality: 'MEDIUM' },
  { asset_id: 'AST-ANDH-PUMP-02', type: 'PUMP', name: 'Andheri storm-water pump P-02', lat: 19.1181, lon: 72.8491, source: 'authored_seed', freshness: '2026-10-12T13:58:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-POW-ROAD-SEG-03', type: 'ROAD_SEGMENT', name: 'Powai road segment S-03', lat: 19.1188, lon: 72.9063, source: 'authored_seed', freshness: '2026-10-12T13:44:00+05:30', criticality: 'MEDIUM' },
  { asset_id: 'AST-TRANSIT-ANDHERI', type: 'TRANSIT_STOP', name: 'Andheri Metro Station', lat: 19.1197, lon: 72.8464, source: 'authored_seed', freshness: '2026-10-11T00:00:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-HOSP-ANDHERI', type: 'HOSPITAL', name: 'Andheri General Hospital', lat: 19.1136, lon: 72.8512, source: 'authored_seed', freshness: '2026-10-11T00:00:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-FIRE-ANDHERI', type: 'FIRE_STATION', name: 'Andheri Fire Station', lat: 19.1163, lon: 72.8437, source: 'authored_seed', freshness: '2026-10-11T00:00:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-HOSP-KURLA', type: 'HOSPITAL', name: 'Kurla General Hospital', lat: 19.0702, lon: 72.8891, source: 'authored_seed', freshness: '2026-10-11T00:00:00+05:30', criticality: 'HIGH' },
  { asset_id: 'AST-SUBSTATION-ANDH', type: 'SUBSTATION', name: 'Andheri feeder substation', lat: 19.1151, lon: 72.8402, source: 'authored_seed', freshness: '2026-10-12T13:10:00+05:30', criticality: 'MEDIUM' }
];

// Infrastructure dependency edges used by the cascade view. Every one carries its source and
// a semantics label so the UI never renders a configured dependency as a proven causal fact.
export const ASSET_DEPENDENCIES = [
  { from: 'AST-ANDH-ROAD-SEG-12', type: 'DEPENDS_ON', to: 'AST-ANDH-DRAIN-04', semantics: 'CONFIGURED', source: 'authored_seed', assumption: 'Road segment drains through DM-04 when surface runoff exceeds shoulder capacity.', validated: false },
  { from: 'AST-ANDH-UNDERPASS', type: 'DEPENDS_ON', to: 'AST-ANDH-DRAIN-04', semantics: 'CONFIGURED', source: 'authored_seed', assumption: 'Underpass sump is served by drain DM-04.', validated: false },
  { from: 'AST-ANDH-DRAIN-04', type: 'CONNECTED_TO', to: 'AST-ANDH-PUMP-02', semantics: 'CONFIGURED', source: 'authored_seed', assumption: 'DM-04 discharges to storm-water pump P-02.', validated: false },
  { from: 'AST-ANDH-DRAIN-04', type: 'DEPENDS_ON', to: 'AST-ANDH-GAUGE-04', semantics: 'OBSERVED', source: 'cwc_water_gauge', assumption: 'Gauge WG-04 measures headwater at DM-04 inlet.', validated: false },
  { from: 'AST-ANDH-GAUGE-09', type: 'CONNECTED_TO', to: 'AST-ANDH-GAUGE-04', semantics: 'OBSERVED', source: 'cwc_water_gauge', assumption: 'Sahar gauge is the nearest upstream comparison point for WG-04.', validated: false },
  { from: 'AST-ANDH-UNDERPASS', type: 'CONNECTED_TO', to: 'AST-TRANSIT-ANDHERI', semantics: 'CONFIGURED', source: 'authored_seed', assumption: 'Underpass is the primary pedestrian link to the metro station.', validated: false },
  { from: 'AST-ANDH-UNDERPASS', type: 'AFFECTS', to: 'AST-HOSP-ANDHERI', semantics: 'CONFIGURED', source: 'authored_seed', assumption: 'Emergency vehicle access to Andheri General Hospital routes through the underpass approach.', validated: false },
  { from: 'AST-ANDH-ROAD-SEG-13', type: 'AFFECTS', to: 'AST-POW-ROAD-SEG-03', semantics: 'HYPOTHESIS', source: 'scenario_assumption', assumption: 'Displaced traffic from S-13 is assumed to spill toward Powai segment S-03.', validated: false },
  { from: 'AST-ANDH-DRAIN-04', type: 'CONNECTED_TO', to: 'AST-SUBSTATION-ANDH', semantics: 'HYPOTHESIS', source: 'scenario_assumption', assumption: 'Assumes pump P-02 depends on the feeder substation and that flooding can affect access.', validated: false }
];

export function assetById(id) { return ASSETS.find(asset => asset.asset_id === id); }
export function areaByName(name) { return AREAS.find(area => area.name === name); }

// Equirectangular local projection centred on the operating area. Accurate enough at city
// scale and auditable, which matters more here than a full geodesic projection.
export const MAP_CENTER = { lat: 19.0625, lon: 72.872 };
const KM_PER_DEG_LAT = 110.574;
const kmPerDegLon = KM_PER_DEG_LAT * Math.cos((MAP_CENTER.lat * Math.PI) / 180);

// World units are kilometres so scene distances read naturally.
export function project({ lat, lon }) {
  return [-(lon - MAP_CENTER.lon) * kmPerDegLon, 0, (lat - MAP_CENTER.lat) * KM_PER_DEG_LAT];
}

export function unproject([x, , z]) {
  return { lat: MAP_CENTER.lat + z / KM_PER_DEG_LAT, lon: MAP_CENTER.lon - x / kmPerDegLon };
}