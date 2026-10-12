export const DEPARTMENTS = [
  { department_id: 'drainage', name: 'Drainage and Stormwater' },
  { department_id: 'water_resources', name: 'Water Resources' },
  { department_id: 'roads_traffic', name: 'Roads and Traffic' },
  { department_id: 'environment', name: 'Environment and Air Quality' },
  { department_id: 'emergency_management', name: 'Emergency Management' }
];

// Seeded UI preview only. Live API reports are served by the FastAPI intelligence service.
export const DEPARTMENT_REPORTS = [
  {
    report_id: 'RPT-INC-104-DRAINAGE',
    incident_id: 'INC-104',
    department_id: 'drainage',
    department_name: 'Drainage and Stormwater',
    routing_reason: 'Drainage asset DM-04 and the blocked-drain hypothesis map to this department.',
    routing_confidence: 0.82,
    subject: 'Incident INC-104: Andheri underpass waterlogging',
    summary: 'Waterlogging is reported near drain DM-04. A blocked drain is a proposed cause and remains unconfirmed.',
    cause_claim: 'Blocked drain DM-04',
    cause_status: 'PROPOSED',
    cause_score: 0.61,
    evidence_event_ids: ['evt-0004', 'evt-0005', 'evt-0006'],
    asset_ids: ['AST-ANDH-DRAIN-04'],
    requested_follow_up: 'Inspect drain DM-04 and report whether capacity is obstructed.',
    uncertainties: ['No inspection record exists for DM-04.', 'This report is a seeded UI preview.'],
    status: 'draft',
    delivery_status: 'not_configured'
  }
];
