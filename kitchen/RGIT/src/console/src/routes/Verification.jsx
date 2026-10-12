import { useMemo, useRef, useState } from 'react';
import { AlertTriangle, CalendarClock, Clock3, FileImage, GitCompareArrows, MapPin, Network, ScanSearch, ShieldCheck, Trash2, Upload } from 'lucide-react';
import { Badge, Button, Card, Input } from '@/components/ui';
import { PageBody, PageHeader } from '@/lib/Shell.jsx';

const panels = [
  ['authenticity', 'Evidence authenticity', 'Metadata, image consistency and human review'],
  ['duplicates', 'Duplicate evidence', 'Near-identical uploads are grouped as one visual source'],
  ['location', 'Location consistency', 'Reported place compared with available GPS coordinates'],
  ['time', 'Temporal consistency', 'Capture, report and upload times are compared'],
  ['sources', 'Cross-source evidence', 'Citizen observations, sensors and weather can conflict'],
  ['coordination', 'Reporting patterns', 'Repeated text, timing and locations can indicate a burst'],
  ['causes', 'Competing causes', 'Keep plausible explanations open until evidence distinguishes them'],
  ['cascade', 'Cascade impacts', 'Trace potential downstream infrastructure effects'],
];

function readExifDate(buffer) {
  try {
  const view = new DataView(buffer);
  for (let i = 2; i < view.byteLength - 4;) {
    if (view.getUint16(i) !== 0xffe1) { i += 1; continue; }
    const length = view.getUint16(i + 2);
    if (String.fromCharCode(...new Uint8Array(buffer, i + 4, 6)) !== 'Exif\0\0') { i += length + 2; continue; }
    const tiff = i + 10;
    const little = view.getUint16(tiff) === 0x4949;
    const u16 = p => view.getUint16(p, little);
    const u32 = p => view.getUint32(p, little);
    const ifd = tiff + u32(tiff + 4);
    const count = u16(ifd);
    for (let n = 0; n < count; n += 1) {
      const entry = ifd + 2 + n * 12;
      if (u16(entry) === 0x0132) {
        const offset = tiff + u32(entry + 8);
        const size = Math.min(u32(entry + 4), 32);
        const raw = String.fromCharCode(...new Uint8Array(buffer, offset, size)).replace(/\0/g, '').trim();
        const match = raw.match(/^(\d{4}):(\d\d):(\d\d) (\d\d:\d\d:\d\d)$/);
        if (match) return new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}`);
      }
    }
    break;
  }
  return null;
  } catch { return null; }
}

async function imageFingerprint(file) {
  try {
    const bitmap = await createImageBitmap(file);
    const canvas = document.createElement('canvas');
    canvas.width = 9; canvas.height = 8;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(bitmap, 0, 0, 9, 8);
    bitmap.close?.();
    const data = ctx.getImageData(0, 0, 9, 8).data;
    let hash = '';
    for (let y = 0; y < 8; y += 1) for (let x = 0; x < 8; x += 1) {
      const a = (y * 9 + x) * 4; const b = (y * 9 + x + 1) * 4;
      const ga = data[a] * 0.299 + data[a + 1] * 0.587 + data[a + 2] * 0.114;
      const gb = data[b] * 0.299 + data[b + 1] * 0.587 + data[b + 2] * 0.114;
      hash += ga > gb ? '1' : '0';
    }
    return hash;
  } catch { return null; }
}

function hamming(a, b) {
  if (!a || !b || a.length !== b.length) return 64;
  let n = 0;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) n += 1;
  return n;
}

function ResultRow({ icon: Icon, title, children, tone = 'neutral' }) {
  return <div className="flex gap-3 border-b border-border py-3 last:border-0">
    <Icon className="mt-0.5 size-4 shrink-0 text-fg-subtle" />
    <div className="min-w-0 flex-1"><div className="text-[12.5px] font-medium text-fg">{title}</div><div className="mt-0.5 text-[12px] leading-relaxed text-fg-muted">{children}</div></div>
    <Badge tone={tone}>{tone === 'healthy' ? 'Consistent' : tone === 'degraded' ? 'Review' : 'Unresolved'}</Badge>
  </div>;
}

export default function Verification() {
  const inputRef = useRef(null);
  const removedIds = useRef(new Set());
  const [items, setItems] = useState([]);
  const [place, setPlace] = useState('');
  const [coordinates, setCoordinates] = useState('');
  const [reportedAt, setReportedAt] = useState('');
  const [weather, setWeather] = useState('');
  const [sensor, setSensor] = useState('');
  const [notes, setNotes] = useState('');
  const [active, setActive] = useState('authenticity');

  async function addFiles(files) {
    const next = [];
    for (const file of [...files]) {
      if (!file.type.startsWith('image/')) continue;
      const [hash, buffer] = await Promise.all([imageFingerprint(file), file.arrayBuffer()]);
      const date = file.type === 'image/jpeg' ? readExifDate(buffer) : null;
      const prior = [...items, ...next].find(item => hash && hamming(hash, item.hash) <= 8);
      const item = { id: `${file.name}-${file.lastModified}-${Math.random()}`, file, url: URL.createObjectURL(file), hash, date, duplicate: prior?.cluster || prior?.id || null, cluster: prior?.cluster || prior?.id || null, analysisStatus: 'idle' };
      next.push(item);
    }
    setItems(current => [...current, ...next]);
  }

  function removeImage(id) {
    removedIds.current.add(id);
    setItems(current => {
      const item = current.find(entry => entry.id === id);
      if (item?.url) URL.revokeObjectURL(item.url);
      return current.filter(entry => entry.id !== id);
    });
  }

  async function analyzeEvidence() {
    if (!items.length || items.some(item => item.analysisStatus === 'checking')) return;
    const selected = [...items];
    setItems(current => current.map(existing => selected.some(item => item.id === existing.id)
      ? { ...existing, analysisStatus: 'checking', analysis: null, analysisError: null }
      : existing));
    for (const item of selected) {
      if (removedIds.current.has(item.id)) continue;
      try {
        const form = new FormData();
        form.append('image', item.file);
        const response = await fetch('/api/v1/verification/image', { method: 'POST', body: form });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || result.message || result.error || `Image analysis failed (${response.status}).`);
        setItems(current => current.map(existing => existing.id === item.id ? { ...existing, analysisStatus: 'complete', analysis: result } : existing));
      } catch (error) {
        setItems(current => current.map(existing => existing.id === item.id ? { ...existing, analysisStatus: 'error', analysisError: error.message } : existing));
      }
    }
  }

  const hasPhoto = items.length > 0;
  const duplicateCount = items.filter(item => item.duplicate).length;
  const latestAnalysis = [...items].reverse().find(item => item.analysis)?.analysis;
  const analysisPending = items.some(item => item.analysisStatus === 'checking');
  const gps = useMemo(() => {
    const m = coordinates.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
    return m ? { lat: Number(m[1]), lon: Number(m[2]) } : null;
  }, [coordinates]);
  const outOfRange = gps && (Math.abs(gps.lat) > 90 || Math.abs(gps.lon) > 180);
  const dated = items.filter(item => item.date);
  const stale = dated.some(item => Date.now() - item.date.getTime() > 30 * 24 * 60 * 60 * 1000);
  const reportDate = reportedAt ? new Date(reportedAt) : null;
  const timeConflict = reportDate && dated.some(item => Math.abs(reportDate - item.date) > 48 * 60 * 60 * 1000);
  const relatedTextBurst = notes.trim().length > 0 && notes.trim().length < 24;

  return <div className="h-full min-h-0 overflow-y-auto overscroll-y-contain">
    <PageHeader title="Evidence verification" description="Review image, location and time consistency alongside independent signals. Results are indicators for human review, never a definitive authenticity verdict." actions={<Badge tone={hasPhoto ? 'degraded' : 'neutral'}>{hasPhoto ? `${items.length} image${items.length === 1 ? '' : 's'}` : 'No evidence uploaded'}</Badge>} />
    <PageBody className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.8fr)]">
        <div className="space-y-4">
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-[14px] font-semibold">Complaint evidence</h2><p className="mt-1 text-[12px] text-fg-muted">Images stay in this page until you analyze them. Analysis uploads are not stored by the endpoint.</p></div>
              <input ref={inputRef} className="hidden" type="file" accept="image/*" multiple onChange={event => { addFiles(event.target.files); event.target.value = ''; }} />
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => inputRef.current?.click()}><Upload />Upload image</Button>
                <Button variant="primary" disabled={!items.length || analysisPending} onClick={analyzeEvidence}><ScanSearch />{analysisPending ? 'Analyzing…' : 'Analyze evidence'}</Button>
              </div>
            </div>
            <button onClick={() => inputRef.current?.click()} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); addFiles(event.dataTransfer.files); }} className="mt-4 flex min-h-28 w-full flex-col items-center justify-center rounded-[8px] border border-dashed border-border-strong bg-surface-2 px-4 text-center hover:border-accent">
              <FileImage className="size-5 text-fg-subtle" /><span className="mt-2 text-[12.5px] font-medium">Drop evidence images here</span><span className="mt-1 text-[11.5px] text-fg-subtle">JPEG, PNG, WebP · multiple files supported</span>
            </button>
            {items.length > 0 && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">{items.map(item => <div key={item.id} className="overflow-hidden rounded-[6px] border border-border">
              <div className="relative"><img src={item.url} alt={`Evidence ${item.file.name}`} className="h-28 w-full object-cover" /><button type="button" onClick={() => removeImage(item.id)} aria-label={`Remove ${item.file.name}`} title="Remove image" className="absolute right-1.5 top-1.5 grid size-7 place-items-center rounded-[5px] border border-border bg-surface/95 text-fg-muted hover:bg-critical-soft hover:text-critical"><Trash2 className="size-3.5" /></button></div><div className="p-2"><div className="truncate text-[11.5px] font-medium">{item.file.name}</div><div className="mt-1 text-[10.5px] text-fg-subtle">{(item.file.size / 1024).toFixed(0)} KB · {item.date ? `EXIF ${item.date.toLocaleString()}` : 'No capture time'}</div><div className="mt-1 text-[10.5px] text-fg-muted">{item.analysisStatus === 'checking' ? 'Analyzing…' : item.analysis?.model_score_fake != null ? `${(item.analysis.model_score_fake * 100).toFixed(1)}% model signal` : item.analysisError || item.analysis?.model_error || (item.analysis ? 'Analysis complete; no model score' : 'Ready to analyze')}</div>{item.duplicate && <Badge className="mt-1" tone="degraded">Possible duplicate cluster</Badge>}</div>
            </div>)}</div>}
            {latestAnalysis && <div className={`mt-3 rounded-[6px] border p-3 ${latestAnalysis.model_score_fake == null ? 'border-accent/25 bg-accent-soft' : latestAnalysis.model_score_fake >= (latestAnalysis.model_threshold ?? 0.5) ? 'border-critical/30 bg-critical-soft' : 'border-healthy/30 bg-healthy-soft'}`}>
              <div className="text-[12.5px] font-semibold text-fg">Image analysis complete</div>
              {latestAnalysis.model_score_fake != null
                ? <p className="mt-1 text-[12px] leading-relaxed text-fg-muted"><span className={`font-semibold ${latestAnalysis.model_score_fake >= (latestAnalysis.model_threshold ?? 0.5) ? 'text-critical' : 'text-healthy'}`}>{latestAnalysis.model_score_fake >= (latestAnalysis.model_threshold ?? 0.5) ? 'POSSIBLE AI / EDITED' : 'NO STRONG AI SIGNAL'}</span> · XproAI v3 review score: <span className="font-semibold text-fg">{(latestAnalysis.model_score_fake * 100).toFixed(1)}%</span>. This retired model’s score is only an indicator, not proof of authenticity; human review is required.</p>
                : <p className="mt-1 text-[12px] leading-relaxed text-fg-muted">{latestAnalysis.model_error || 'The request completed, but no model score was returned.'}</p>}
              <p className="mt-1 text-[11px] text-fg-subtle">C2PA: {latestAnalysis.c2pa?.message || 'No C2PA result returned.'}</p>
            </div>}
          </Card>

          <Card className="p-4">
            <h2 className="text-[14px] font-semibold">Reported context</h2>
            <p className="mt-1 text-[12px] text-fg-muted">Enter what the complaint claims and any observations available to the reviewer.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="text-[11.5px] text-fg-muted">Reported location<Input value={place} onChange={e => setPlace(e.target.value)} className="mt-1" placeholder="Road, area, landmark" /></label>
              <label className="text-[11.5px] text-fg-muted">Reported coordinates<Input value={coordinates} onChange={e => setCoordinates(e.target.value)} className="mt-1" placeholder="Latitude, longitude" /></label>
              <label className="text-[11.5px] text-fg-muted">Incident time<Input type="datetime-local" value={reportedAt} onChange={e => setReportedAt(e.target.value)} className="mt-1" /></label>
              <label className="text-[11.5px] text-fg-muted">Weather observation<Input value={weather} onChange={e => setWeather(e.target.value)} className="mt-1" placeholder="Rainfall / source / time" /></label>
              <label className="text-[11.5px] text-fg-muted">Nearby sensor or report<Input value={sensor} onChange={e => setSensor(e.target.value)} className="mt-1" placeholder="Reading, distance and observation time" /></label>
              <label className="text-[11.5px] text-fg-muted">Complaint text<Input value={notes} onChange={e => setNotes(e.target.value)} className="mt-1" placeholder="What happened? Include road / impact" /></label>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="p-4">
            <div className="flex items-center gap-2"><ShieldCheck className="size-4 text-accent" /><h2 className="text-[14px] font-semibold">Review indicators</h2></div>
            <p className="mt-1 text-[12px] text-fg-muted">A missing or conflicting signal lowers confidence; it does not establish fraud.</p>
            <div className="mt-3">
              <ResultRow icon={ScanSearch} title="XproAI image triage" tone={latestAnalysis?.status === 'scored' ? 'degraded' : 'neutral'}>{latestAnalysis?.status === 'scored' ? `XproAI v3 score: ${(latestAnalysis.model_score_fake * 100).toFixed(1)}% fake signal (${latestAnalysis.model_indicator.replaceAll('_', ' ')}). Human review required; the project's own notes report weak real-world performance for this retired model.` : latestAnalysis?.model_error || (analysisPending ? 'Image uploaded; running the configured XproAI checkpoint and C2PA checks…' : items.some(item => item.analysisStatus === 'error') ? items.find(item => item.analysisStatus === 'error')?.analysisError : 'Upload an image to run the configured XproAI checkpoint and C2PA checks.')}</ResultRow>
              <ResultRow icon={ShieldCheck} title="C2PA content credentials" tone={latestAnalysis?.c2pa?.status === 'validated' ? 'healthy' : latestAnalysis?.c2pa?.manifest_present ? 'degraded' : 'neutral'}>{latestAnalysis ? latestAnalysis.c2pa.message : 'The raw upload is checked for an embedded, validated provenance manifest. No manifest is not evidence of authenticity.'}</ResultRow>
              <ResultRow icon={GitCompareArrows} title="Duplicate visual evidence" tone={duplicateCount ? 'degraded' : hasPhoto ? 'healthy' : 'neutral'}>{hasPhoto ? duplicateCount ? `${duplicateCount} upload(s) resemble another image in this session. Count the cluster as one visual corroboration.` : 'No near-duplicate found among images uploaded in this session.' : 'Upload images to compute a perceptual similarity fingerprint.'}</ResultRow>
              <ResultRow icon={MapPin} title="Location consistency" tone={outOfRange ? 'degraded' : gps && place ? 'degraded' : 'neutral'}>{outOfRange ? 'Coordinates are outside valid latitude/longitude ranges.' : gps && place ? `Coordinates ${gps.lat.toFixed(4)}, ${gps.lon.toFixed(4)} are recorded; place-name matching and landmark recognition need a geocoding/vision source.` : 'Unresolved: GPS or a specific reported place is missing. GPS may be spoofed and is not conclusive.'}</ResultRow>
              <ResultRow icon={CalendarClock} title="Temporal consistency" tone={timeConflict || stale ? 'degraded' : dated.length ? 'healthy' : 'neutral'}>{timeConflict ? 'EXIF capture time differs from the reported incident time by more than 48 hours.' : stale ? 'Image metadata suggests the image may be older than 30 days.' : dated.length ? 'Capture timestamp is available; compare it with the incident observation window.' : 'Unverified: capture metadata is unavailable. Upload time alone cannot prove when the image was taken.'}</ResultRow>
              <ResultRow icon={Network} title="Cross-source consistency" tone={weather && sensor ? 'degraded' : 'neutral'}>{weather && sensor ? 'Both sources entered. Compare their distance, freshness, health and coverage; conflicting observations need review.' : 'Insufficient evidence until weather and sensor or nearby report observations are supplied.'}</ResultRow>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2"><AlertTriangle className="size-4 text-degraded" /><h2 className="text-[14px] font-semibold">Verification workspace</h2></div>
            <div className="mt-3 flex flex-wrap gap-1.5">{panels.map(([id, label]) => <button key={id} onClick={() => setActive(id)} className={`rounded-[5px] border px-2 py-1 text-[11px] ${active === id ? 'border-accent/30 bg-accent-soft text-accent' : 'border-border text-fg-muted hover:bg-surface-2'}`}>{label}</button>)}</div>
            <div className="mt-4 rounded-[6px] bg-surface-2 p-3">
              <div className="text-[12.5px] font-semibold">{panels.find(panel => panel[0] === active)?.[1]}</div>
              <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">{active === 'authenticity' ? 'Uploaded bytes are sent to the Urban Sentinel API for XproAI v3 triage and C2PA SDK validation. C2PA claims are treated as AI-origin evidence only when signature/trust validation succeeds. The retired CNN score is weak in unfamiliar real-world images, so every result remains a human-review signal.' : active === 'duplicates' ? `Perceptual hashes compare uploads on this page and group likely copies. Current possible repeats: ${duplicateCount}. Similarity is a lead, not proof of the same source.` : active === 'location' ? 'GPS coordinates are treated as untrusted hints. Add a precise place; mapped infrastructure and visible signs require connected geocoding / vision services.' : active === 'time' ? 'EXIF date is read where available and compared with the claimed incident time. Metadata can be stripped or edited.' : active === 'sources' ? 'Record source, observation time, distance and health before comparing reports, rain and water levels. Offline sensors are missing coverage, not evidence of normal conditions.' : active === 'coordination' ? `Repeated short complaint text is marked for review (${relatedTextBurst ? 'pattern needs more context' : 'no short-text burst hint'}). Account linkage and burst analysis need report history.` : active === 'causes' ? 'Keep rainfall, blocked drainage, pump failure and combined causes as open hypotheses. Request drain inspection, pump telemetry or a second nearby observation to distinguish them.' : 'Show possible downstream roads, hospital routes and transit assets only when the infrastructure dependency graph is connected; modelled impacts need field confirmation.'}</p>
            </div>
          </Card>
        </div>
      </div>
      <div className="flex items-start gap-2 rounded-[6px] border border-degraded/25 bg-degraded-soft p-3 text-[11.5px] leading-relaxed text-degraded"><Clock3 className="mt-0.5 size-4 shrink-0" /><span><strong className="font-semibold">Analysis scope and limitations:</strong> Image triage calls the backend and sends the original file bytes. The model is retired and is not a definitive detector. No landmark recognition, live weather/sensor lookup, account-coordination analysis or incident storage is connected. A missing C2PA manifest does not establish authenticity. Keep human verification in the loop.</span></div>
    </PageBody>
  </div>;
}
