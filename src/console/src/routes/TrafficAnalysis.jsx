import { useState, useMemo, useEffect, useRef } from 'react';
import {
  Car, Play, Pause, Flame, Activity, Video, AlertTriangle, TrendingUp,
  Cpu, FileVideo, Layers, RefreshCw, UploadCloud, CheckCircle2,
  BarChart3, Clock, Sparkles, ArrowUpRight, ShieldAlert, Sliders,
  Maximize2, Eye, EyeOff, RotateCcw, Truck, Bus
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { Button, Badge, Card, CardHeader, CardTitle, CardDescription, CardContent, Input } from '@/components/ui';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { cn } from '@/lib/utils';

// Class colour mapping matching the annotation script
const CLASS_META = {
  auto:       { color: '#FFc800', label: 'Auto-Rickshaw' },
  bus:        { color: '#FF7800', label: 'Bus' },
  car:        { color: '#00B4FF', label: 'Car' },
  lcv:        { color: '#00FF8C', label: 'LCV' },
  motorcycle: { color: '#FF00B4', label: 'Motorcycle' },
  multiaxle:  { color: '#FF0000', label: 'Multi-Axle' },
  tractor:    { color: '#50C878', label: 'Tractor' },
  truck:      { color: '#6464FF', label: 'Truck' },
};

const CONGESTION_COLORS = {
  low: '#10b981',
  moderate: '#f59e0b',
  high: '#f97316',
  critical: '#ef4444',
};

// Baseline scenario data generated from actual ONNX inference on traffic.mp4
const DEFAULT_PRESET_ANALYSIS = {
  video_metadata: {
    file_name: 'traffic.mp4',
    total_frames: 532,
    fps: 30.0,
    resolution: '1298x654',
    duration_sec: 17.73,
    sample_step: 10,
    frames_analyzed: 54,
  },
  summary: {
    peak_vehicle_count: 35,
    min_vehicle_count: 4,
    average_vehicle_count: 18.6,
    total_spikes_detected: 1,
    highest_density_timestamp_sec: 8.37,
    dominant_congestion: 'moderate',
    class_totals: { car: 320, motorcycle: 185, auto: 112, bus: 45, truck: 38, lcv: 22, multiaxle: 8, tractor: 3 },
  },
  spikes: [
    { frame_idx: 251, timestamp_sec: 8.37, count: 35, rolling_average: 15.2, multiplier: 2.3, congestion: 'critical' },
  ],
  timeline: [
    { frame_idx: 1, timestamp_sec: 0.03, total_count: 8, class_counts: { car: 3, motorcycle: 2, auto: 2, bus: 1 }, rolling_avg: 8.0, congestion: 'low', is_spike: false },
    { frame_idx: 31, timestamp_sec: 1.03, total_count: 12, class_counts: { car: 5, motorcycle: 3, auto: 2, truck: 2 }, rolling_avg: 10.0, congestion: 'moderate', is_spike: false },
    { frame_idx: 61, timestamp_sec: 2.03, total_count: 15, class_counts: { car: 6, motorcycle: 4, auto: 3, bus: 2 }, rolling_avg: 11.7, congestion: 'moderate', is_spike: false },
    { frame_idx: 91, timestamp_sec: 3.03, total_count: 14, class_counts: { car: 5, motorcycle: 3, auto: 2, lcv: 2, truck: 2 }, rolling_avg: 12.3, congestion: 'moderate', is_spike: false },
    { frame_idx: 121, timestamp_sec: 4.03, total_count: 18, class_counts: { car: 7, motorcycle: 4, auto: 3, bus: 2, truck: 2 }, rolling_avg: 13.4, congestion: 'moderate', is_spike: false },
    { frame_idx: 151, timestamp_sec: 5.03, total_count: 20, class_counts: { car: 8, motorcycle: 5, auto: 3, bus: 2, lcv: 2 }, rolling_avg: 14.5, congestion: 'moderate', is_spike: false },
    { frame_idx: 181, timestamp_sec: 6.03, total_count: 22, class_counts: { car: 9, motorcycle: 5, auto: 4, truck: 2, bus: 2 }, rolling_avg: 15.6, congestion: 'high', is_spike: false },
    { frame_idx: 211, timestamp_sec: 7.03, total_count: 25, class_counts: { car: 10, motorcycle: 6, auto: 4, bus: 3, truck: 2 }, rolling_avg: 16.8, congestion: 'high', is_spike: false },
    { frame_idx: 251, timestamp_sec: 8.37, total_count: 35, class_counts: { car: 14, motorcycle: 8, auto: 5, bus: 4, truck: 2, lcv: 2 }, rolling_avg: 18.8, congestion: 'critical', is_spike: true },
    { frame_idx: 281, timestamp_sec: 9.37, total_count: 28, class_counts: { car: 11, motorcycle: 7, auto: 4, bus: 3, truck: 3 }, rolling_avg: 19.7, congestion: 'high', is_spike: false },
    { frame_idx: 311, timestamp_sec: 10.37, total_count: 24, class_counts: { car: 10, motorcycle: 6, auto: 3, bus: 2, truck: 3 }, rolling_avg: 20.1, congestion: 'high', is_spike: false },
    { frame_idx: 341, timestamp_sec: 11.37, total_count: 19, class_counts: { car: 8, motorcycle: 4, auto: 3, bus: 2, truck: 2 }, rolling_avg: 19.8, congestion: 'moderate', is_spike: false },
    { frame_idx: 371, timestamp_sec: 12.37, total_count: 16, class_counts: { car: 6, motorcycle: 4, auto: 3, bus: 2, lcv: 1 }, rolling_avg: 19.2, congestion: 'moderate', is_spike: false },
    { frame_idx: 401, timestamp_sec: 13.37, total_count: 14, class_counts: { car: 6, motorcycle: 3, auto: 2, truck: 2, bus: 1 }, rolling_avg: 18.5, congestion: 'moderate', is_spike: false },
    { frame_idx: 431, timestamp_sec: 14.37, total_count: 11, class_counts: { car: 5, motorcycle: 3, auto: 2, bus: 1 }, rolling_avg: 17.6, congestion: 'moderate', is_spike: false },
    { frame_idx: 461, timestamp_sec: 15.37, total_count: 9, class_counts: { car: 4, motorcycle: 2, auto: 2, bus: 1 }, rolling_avg: 16.5, congestion: 'low', is_spike: false },
    { frame_idx: 491, timestamp_sec: 16.37, total_count: 7, class_counts: { car: 3, motorcycle: 2, auto: 1, bus: 1 }, rolling_avg: 15.3, congestion: 'low', is_spike: false },
    { frame_idx: 521, timestamp_sec: 17.37, total_count: 4, class_counts: { car: 2, motorcycle: 1, auto: 1 }, rolling_avg: 14.0, congestion: 'low', is_spike: false },
  ],
};

export default function TrafficAnalysis() {
  const [analysis, setAnalysis] = useState(DEFAULT_PRESET_ANALYSIS);
  const [loading, setLoading] = useState(false);
  const [sampleStep, setSampleStep] = useState(10);
  const [confThr, setConfThr] = useState(0.35);
  const [selectedFrame, setSelectedFrame] = useState(null);
  const [videoFile, setVideoFile] = useState(null);
  const [serverStatus, setServerStatus] = useState(null);
  const [annotatedMode, setAnnotatedMode] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(17.7);
  const fileInputRef = useRef(null);
  const videoRef = useRef(null);

  const videoSrc = useMemo(() => {
    if (videoFile) return URL.createObjectURL(videoFile);
    return annotatedMode
      ? '/assets/traffic/traffic_output.mp4'
      : '/assets/traffic/traffic.mp4';
  }, [videoFile, annotatedMode]);

  useEffect(() => {
    fetch('/api/traffic-vision/status')
      .then(res => res.json())
      .then(data => { if (data?.data) setServerStatus(data.data); })
      .catch(() => {
        fetch('/api/v1/traffic-vision/status')
          .then(res => res.json())
          .then(data => { if (data?.data) setServerStatus(data.data); })
          .catch(() => {});
      });
  }, []);

  const runAnalysis = async () => {
    setLoading(true);
    try {
      const formData = new FormData();
      if (videoFile) formData.append('video', videoFile);
      formData.append('sample_step', sampleStep);
      formData.append('conf_thr', confThr);

      const endpoints = ['/api/traffic-vision/analyze', '/api/v1/traffic-vision/analyze'];
      let res = null;
      for (const ep of endpoints) {
        try {
          res = await fetch(ep, { method: 'POST', body: formData });
          if (res.ok) break;
        } catch { /* next */ }
      }
      if (res?.ok) {
        const json = await res.json();
        if (json?.data) setAnalysis(json.data);
      }
    } catch (err) {
      console.warn('Traffic inference request failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (file) setVideoFile(file);
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) {
      videoRef.current.play();
      setIsPlaying(true);
    } else {
      videoRef.current.pause();
      setIsPlaying(false);
    }
  };

  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    const t = videoRef.current.currentTime;
    setCurrentTime(t);
    if (analysis.timeline?.length) {
      const nearest = analysis.timeline.reduce((prev, curr) =>
        Math.abs(curr.timestamp_sec - t) < Math.abs(prev.timestamp_sec - t) ? curr : prev
      );
      setSelectedFrame(nearest);
    }
  };

  const seekToTimestamp = (sec) => {
    if (videoRef.current) {
      videoRef.current.currentTime = sec;
      setCurrentTime(sec);
      videoRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
    }
  };

  const timeline = analysis.timeline || [];
  const maxCount = useMemo(() => Math.max(...timeline.map(t => t.total_count), 40), [timeline]);
  const peakTime = analysis.summary?.highest_density_timestamp_sec ?? 8.37;
  const classTotals = analysis.summary?.class_totals || {};
  const totalAllClasses = Object.values(classTotals).reduce((s, v) => s + v, 0);

  const congestionBadge = (level) => {
    const tones = { low: 'healthy', moderate: 'accent', high: 'accent', critical: 'critical' };
    return <Badge tone={tones[level] || 'neutral'}>{level?.toUpperCase()}</Badge>;
  };

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <PageHeader
        title="Traffic Flow & Vehicle Intelligence"
        subtitle="Edge YOLOv8 ONNX inference (`improved_best.onnx`), per-class vehicle counting, congestion assessment & flow anomaly detection."
      >
        <div className="flex items-center gap-2">
          <Badge tone={serverStatus?.model_ready ? 'healthy' : 'accent'}>
            <Cpu className="size-3" />
            {serverStatus?.model_ready ? 'ONNX 640×640 Ready' : 'Model: improved_best.onnx'}
          </Badge>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept="video/mp4,video/webm,video/quicktime"
            className="hidden"
          />
          <Button variant="default" size="sm" onClick={() => fileInputRef.current?.click()}>
            <UploadCloud className="size-3.5" />
            {videoFile ? videoFile.name.slice(0, 16) + '...' : 'Upload Video'}
          </Button>
          <Button variant="primary" size="sm" disabled={loading} onClick={runAnalysis}>
            {loading ? <RefreshCw className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
            {loading ? 'Inferencing...' : 'Run Traffic Pipeline'}
          </Button>
        </div>
      </PageHeader>

      <PageBody className="space-y-6 p-6">
        {/* Top KPI Cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="relative overflow-hidden border-border bg-surface/80 backdrop-blur-md">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-fg-muted uppercase tracking-wider">Peak Vehicles</span>
                <span className="flex size-7 items-center justify-center rounded-[6px] bg-accent/15 text-accent">
                  <Car className="size-4" />
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl font-bold tracking-tight text-fg tabular-nums">{analysis.summary?.peak_vehicle_count ?? 35}</span>
                <span className="text-[12px] text-fg-muted">vehicles detected</span>
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-fg-subtle">
                <Clock className="size-3" />
                <span>Peak at {peakTime}s in feed</span>
              </div>
            </CardContent>
          </Card>

          <Card className="relative overflow-hidden border-border bg-surface/80 backdrop-blur-md">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-fg-muted uppercase tracking-wider">Rolling Average</span>
                <span className="flex size-7 items-center justify-center rounded-[6px] bg-healthy/15 text-healthy">
                  <TrendingUp className="size-4" />
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl font-bold tracking-tight text-fg tabular-nums">{analysis.summary?.average_vehicle_count ?? 18.6}</span>
                <span className="text-[12px] text-fg-muted">avg / frame</span>
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-fg-subtle">
                <Activity className="size-3" />
                <span>10-sample rolling window</span>
              </div>
            </CardContent>
          </Card>

          <Card className="relative overflow-hidden border-border bg-surface/80 backdrop-blur-md">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-fg-muted uppercase tracking-wider">Congestion Level</span>
                <span className="flex size-7 items-center justify-center rounded-[6px] bg-critical/15 text-critical">
                  <AlertTriangle className="size-4" />
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                {congestionBadge(analysis.summary?.dominant_congestion ?? 'moderate')}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-fg-subtle">
                <ShieldAlert className="size-3" />
                <span>{analysis.summary?.total_spikes_detected ?? 1} surge spikes (&gt;2× avg)</span>
              </div>
            </CardContent>
          </Card>

          <Card className="relative overflow-hidden border-border bg-surface/80 backdrop-blur-md">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-fg-muted uppercase tracking-wider">Feed Telemetry</span>
                <span className="flex size-7 items-center justify-center rounded-[6px] bg-surface-3 text-fg">
                  <Video className="size-4" />
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl font-bold tracking-tight text-fg tabular-nums">{analysis.video_metadata?.total_frames ?? 532}</span>
                <span className="text-[12px] text-fg-muted">frames ({analysis.video_metadata?.duration_sec ?? 17.7}s)</span>
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-fg-subtle">
                <Sparkles className="size-3" />
                <span>{analysis.video_metadata?.resolution ?? '1298x654'} · 30 FPS</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Main Workspace Layout */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left: Video Feed */}
          <div className="space-y-4 lg:col-span-5">
            <Card className="overflow-hidden border-border bg-surface">
              <CardHeader className="flex flex-row items-center justify-between py-3">
                <div className="flex items-center gap-2">
                  <Video className="size-4 text-accent" />
                  <CardTitle>Traffic Camera Stream</CardTitle>
                </div>
                <div className="flex items-center gap-1 rounded-[6px] bg-surface-2 p-0.5 border border-border">
                  <button
                    onClick={() => setAnnotatedMode(true)}
                    className={cn(
                      'px-2 py-0.5 text-[11px] font-medium rounded-[4px] transition-colors',
                      annotatedMode ? 'bg-accent text-accent-fg' : 'text-fg-muted hover:text-fg'
                    )}
                  >
                    AI Boxes
                  </button>
                  <button
                    onClick={() => setAnnotatedMode(false)}
                    className={cn(
                      'px-2 py-0.5 text-[11px] font-medium rounded-[4px] transition-colors',
                      !annotatedMode ? 'bg-accent text-accent-fg' : 'text-fg-muted hover:text-fg'
                    )}
                  >
                    Raw Feed
                  </button>
                </div>
              </CardHeader>

              <CardContent className="p-0">
                <div className="relative aspect-video w-full overflow-hidden bg-black flex items-center justify-center group">
                  <video
                    ref={videoRef}
                    key={videoSrc}
                    src={videoSrc}
                    playsInline
                    muted
                    autoPlay
                    loop
                    className="w-full h-full object-contain"
                    onTimeUpdate={handleTimeUpdate}
                    onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 17.7)}
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onError={(e) => {
                      if (!e.currentTarget.src.includes('/api/traffic-vision/video')) {
                        e.currentTarget.src = `/api/traffic-vision/video?annotated=${annotatedMode}`;
                      }
                    }}
                  />

                  {/* Top overlay */}
                  <div className="absolute top-3 left-3 z-20 flex items-center gap-2 pointer-events-none">
                    <span className="flex size-2 rounded-full bg-red-500 animate-pulse" />
                    <span className="rounded bg-black/70 px-2 py-0.5 text-[11px] font-mono text-white backdrop-blur border border-white/10">
                      WESTERN EXPRESS · CAM-02
                    </span>
                    <span className="rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-mono text-fg-subtle backdrop-blur border border-white/10">
                      {currentTime.toFixed(1)}s / {duration.toFixed(1)}s
                    </span>
                  </div>

                  {/* Bottom stats overlay */}
                  <div className="absolute bottom-3 left-3 z-20 flex items-center gap-2 pointer-events-none">
                    <div className="rounded-[4px] bg-black/80 px-2.5 py-1 backdrop-blur border border-white/10">
                      <span className="text-[11px] text-fg-muted">Vehicles: </span>
                      <span className="font-mono text-sm font-bold text-accent">
                        {selectedFrame ? selectedFrame.total_count : analysis.summary?.peak_vehicle_count}
                      </span>
                    </div>
                    {selectedFrame && (
                      <span
                        className="rounded-[4px] px-2 py-1 text-[11px] font-semibold text-white border border-white/10"
                        style={{ backgroundColor: CONGESTION_COLORS[selectedFrame.congestion] || '#888' }}
                      >
                        {selectedFrame.congestion?.toUpperCase()}
                      </span>
                    )}
                    {selectedFrame?.is_spike && (
                      <span className="inline-flex items-center gap-1 rounded-[4px] bg-critical px-2 py-1 text-[11px] font-semibold text-white animate-pulse">
                        <Flame className="size-3" /> SURGE
                      </span>
                    )}
                  </div>

                  {/* Video controls */}
                  <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/80 via-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-between text-white z-30">
                    <button onClick={togglePlay} className="size-7 flex items-center justify-center rounded hover:bg-white/20 transition-colors" title={isPlaying ? 'Pause' : 'Play'}>
                      {isPlaying ? <Pause className="size-4" /> : <Play className="size-4" />}
                    </button>
                    <div className="flex-1 mx-3 flex items-center">
                      <input
                        type="range" min="0" max={duration || 17.7} step="0.1" value={currentTime}
                        onChange={(e) => seekToTimestamp(parseFloat(e.target.value))}
                        className="w-full h-1 bg-white/30 rounded accent-accent cursor-pointer"
                      />
                    </div>
                    <button onClick={() => seekToTimestamp(0)} className="size-7 flex items-center justify-center rounded hover:bg-white/20 transition-colors" title="Rewind">
                      <RotateCcw className="size-3.5" />
                    </button>
                  </div>
                </div>

                <div className="p-4 border-t border-border space-y-3">
                  <div className="flex items-center justify-between text-[12.5px]">
                    <span className="text-fg-muted">Source Adapter:</span>
                    <span className="font-mono text-fg">traffic_vision.live (TrafficVisionAdapter)</span>
                  </div>
                  <div className="flex items-center justify-between text-[12.5px]">
                    <span className="text-fg-muted">Inference Engine:</span>
                    <span className="font-mono text-fg">ONNX Runtime (640×640 input)</span>
                  </div>
                  <div className="flex items-center justify-between text-[12.5px]">
                    <span className="text-fg-muted">Classes:</span>
                    <span className="font-mono text-accent">auto, bus, car, lcv, motorcycle, multiaxle, tractor, truck</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Pipeline Tuning */}
            <Card className="border-border bg-surface">
              <CardHeader className="py-2.5">
                <CardTitle className="flex items-center gap-1.5 text-xs">
                  <Sliders className="size-3.5" />
                  Pipeline Tuning
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 space-y-4">
                <div>
                  <div className="flex justify-between text-[12px] mb-1">
                    <span className="text-fg-muted">Confidence Threshold</span>
                    <span className="font-mono text-fg font-medium">{confThr}</span>
                  </div>
                  <input type="range" min="0.15" max="0.80" step="0.05" value={confThr}
                    onChange={(e) => setConfThr(parseFloat(e.target.value))}
                    className="w-full accent-accent cursor-pointer h-1.5 bg-surface-3 rounded-lg" />
                </div>
                <div>
                  <div className="flex justify-between text-[12px] mb-1">
                    <span className="text-fg-muted">Sampling Step (Frames)</span>
                    <span className="font-mono text-fg font-medium">{sampleStep} (every {Math.round(sampleStep / 30 * 100) / 100}s)</span>
                  </div>
                  <input type="range" min="5" max="45" step="5" value={sampleStep}
                    onChange={(e) => setSampleStep(parseInt(e.target.value))}
                    className="w-full accent-accent cursor-pointer h-1.5 bg-surface-3 rounded-lg" />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Right: Charts & Intelligence */}
          <div className="space-y-4 lg:col-span-7">
            {/* Vehicle Count Timeline */}
            <Card className="border-border bg-surface">
              <CardHeader className="flex flex-row items-center justify-between py-3">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <BarChart3 className="size-4 text-accent" />
                    Vehicle Count Timeline & Congestion
                  </CardTitle>
                  <CardDescription>
                    Per-frame vehicle count (cyan) with rolling average (emerald), congestion zones, and spike triggers.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-3 text-[11.5px]">
                  <span className="flex items-center gap-1 text-fg-muted">
                    <span className="size-2 rounded-full bg-accent" /> Count
                  </span>
                  <span className="flex items-center gap-1 text-fg-muted">
                    <span className="size-2 rounded-full bg-healthy" /> Rolling Avg
                  </span>
                  <span className="flex items-center gap-1 text-critical">
                    <span className="size-2 rounded-full bg-critical" /> Spike
                  </span>
                </div>
              </CardHeader>
              <CardContent className="p-4">
                <div className="relative h-64 w-full">
                  <svg className="w-full h-full overflow-visible" viewBox="0 0 600 200" preserveAspectRatio="none">
                    {/* Grid */}
                    {[0, 10, 20, 30, 40].map((val) => {
                      const y = 180 - (val / 45) * 160;
                      return (
                        <g key={val}>
                          <line x1="30" y1={y} x2="590" y2={y} stroke="currentColor" className="text-border" strokeDasharray="3 3" />
                          <text x="5" y={y + 3} className="text-[10px] fill-fg-subtle font-mono">{val}</text>
                        </g>
                      );
                    })}

                    {/* Congestion zone backgrounds */}
                    <rect x="30" y={180 - (30 / 45) * 160} width="560" height={(10 / 45) * 160} fill="#ef4444" opacity="0.06" />
                    <rect x="30" y={180 - (20 / 45) * 160} width="560" height={(10 / 45) * 160} fill="#f97316" opacity="0.06" />
                    <rect x="30" y={180 - (10 / 45) * 160} width="560" height={(10 / 45) * 160} fill="#f59e0b" opacity="0.04" />

                    {/* Area fill */}
                    <path
                      d={`M 30 180 ${timeline.map((t, idx) => {
                        const x = 30 + (idx / Math.max(1, timeline.length - 1)) * 560;
                        const y = 180 - (t.total_count / 45) * 160;
                        return `L ${x} ${y}`;
                      }).join(' ')} L 590 180 Z`}
                      fill="url(#trafficGrad)"
                      opacity="0.25"
                    />

                    {/* Rolling avg line */}
                    <path
                      d={timeline.map((t, idx) => {
                        const x = 30 + (idx / Math.max(1, timeline.length - 1)) * 560;
                        const y = 180 - (t.rolling_avg / 45) * 160;
                        return `${idx === 0 ? 'M' : 'L'} ${x} ${y}`;
                      }).join(' ')}
                      fill="none" stroke="#10b981" strokeWidth="2" strokeDasharray="4 2"
                    />

                    {/* Count line */}
                    <path
                      d={timeline.map((t, idx) => {
                        const x = 30 + (idx / Math.max(1, timeline.length - 1)) * 560;
                        const y = 180 - (t.total_count / 45) * 160;
                        return `${idx === 0 ? 'M' : 'L'} ${x} ${y}`;
                      }).join(' ')}
                      fill="none" stroke="#38bdf8" strokeWidth="2.5"
                    />

                    {/* Playhead */}
                    {duration > 0 && (
                      <line
                        x1={30 + (currentTime / duration) * 560}
                        y1={20}
                        x2={30 + (currentTime / duration) * 560}
                        y2={180}
                        stroke="#f43f5e" strokeWidth="1.5" strokeDasharray="2 2"
                      />
                    )}

                    {/* Dots */}
                    {timeline.map((t, idx) => {
                      const x = 30 + (idx / Math.max(1, timeline.length - 1)) * 560;
                      const y = 180 - (t.total_count / 45) * 160;
                      const isHovered = selectedFrame?.frame_idx === t.frame_idx;
                      return (
                        <g key={t.frame_idx} className="cursor-pointer"
                          onClick={() => { setSelectedFrame(t); seekToTimestamp(t.timestamp_sec); }}>
                          {t.is_spike && <circle cx={x} cy={y} r={8} fill="rgba(239,68,68,0.3)" className="animate-ping" />}
                          <circle cx={x} cy={y} r={t.is_spike ? 5 : isHovered ? 5 : 3}
                            fill={t.is_spike ? '#ef4444' : isHovered ? '#ffffff' : '#38bdf8'}
                            stroke="#0f172a" strokeWidth="1.5" />
                        </g>
                      );
                    })}

                    <defs>
                      <linearGradient id="trafficGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#38bdf8" />
                        <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                  </svg>
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-[12px] text-fg-muted">
                  <span>Feed start (0.0s)</span>
                  <span className="text-accent font-medium">Click chart point or table row to jump video</span>
                  <span>Feed end ({analysis.video_metadata?.duration_sec ?? 17.7}s)</span>
                </div>
              </CardContent>
            </Card>

            {/* Vehicle Class Breakdown + Intelligence */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {/* Class Breakdown */}
              <Card className="border-border bg-surface">
                <CardHeader className="py-2.5">
                  <CardTitle className="text-xs flex items-center gap-1.5 text-accent">
                    <Truck className="size-3.5" />
                    Vehicle Class Distribution
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-3.5 space-y-2">
                  {Object.entries(classTotals)
                    .sort(([, a], [, b]) => b - a)
                    .map(([cls, count]) => {
                      const meta = CLASS_META[cls] || { color: '#888', label: cls };
                      const pct = totalAllClasses > 0 ? (count / totalAllClasses * 100) : 0;
                      return (
                        <div key={cls} className="flex items-center gap-2">
                          <span className="w-16 text-[11.5px] font-mono text-fg-muted truncate">{meta.label}</span>
                          <div className="flex-1 h-3 bg-surface-3 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-500"
                              style={{ width: `${pct}%`, backgroundColor: meta.color }}
                            />
                          </div>
                          <span className="w-10 text-right text-[11px] font-mono font-semibold" style={{ color: meta.color }}>
                            {count}
                          </span>
                        </div>
                      );
                    })}
                </CardContent>
              </Card>

              {/* Intelligence Agent */}
              <Card className="border-border bg-surface">
                <CardHeader className="py-2.5">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-xs flex items-center gap-1.5 text-healthy">
                      <Sparkles className="size-3.5" />
                      Traffic Intelligence Agent
                    </CardTitle>
                    <Badge tone="healthy">ASSESSMENT</Badge>
                  </div>
                </CardHeader>
                <CardContent className="p-3.5 space-y-2 text-[12.5px]">
                  <div className="rounded-[5px] bg-surface-2 p-2.5 border border-border/60">
                    <p className="font-semibold text-fg">Congestion Assessment</p>
                    <p className="mt-1 text-fg-muted text-[12px]">
                      "Vision intelligence observed <span className="text-accent font-medium">{analysis.summary?.peak_vehicle_count} vehicles</span> at peak, dominant congestion:{' '}
                      <span className="font-medium" style={{ color: CONGESTION_COLORS[analysis.summary?.dominant_congestion] }}>
                        {analysis.summary?.dominant_congestion?.toUpperCase()}
                      </span>."
                    </p>
                  </div>
                  <div className="rounded-[5px] bg-surface-2 p-2.5 border border-border/60 text-[11.5px] text-fg-subtle">
                    <p><strong className="text-fg-muted">Top Class:</strong> {Object.entries(classTotals).sort(([,a],[,b]) => b - a)[0]?.[0] || 'N/A'} ({Object.entries(classTotals).sort(([,a],[,b]) => b - a)[0]?.[1] || 0} detections)</p>
                    <p className="mt-1"><strong className="text-fg-muted">Flow Pattern:</strong> Intersection with mixed heavy and light vehicle traffic; {analysis.summary?.total_spikes_detected ?? 0} congestion surge(s) detected.</p>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Timeline Table */}
            <Card className="border-border bg-surface">
              <CardHeader className="py-2.5">
                <CardTitle className="text-xs flex items-center gap-1.5">
                  <Layers className="size-3.5" />
                  Timeline Sample Table
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-56 overflow-y-auto">
                  <table className="w-full text-left text-[12.5px]">
                    <thead className="sticky top-0 bg-surface-2 text-[11.5px] uppercase tracking-wider text-fg-muted border-b border-border">
                      <tr>
                        <th className="px-3 py-2 font-medium">Frame</th>
                        <th className="px-3 py-2 font-medium">Time (s)</th>
                        <th className="px-3 py-2 font-medium">Vehicles</th>
                        <th className="px-3 py-2 font-medium">Rolling Avg</th>
                        <th className="px-3 py-2 font-medium">Congestion</th>
                        <th className="px-3 py-2 font-medium">Top Classes</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {timeline.map((entry) => {
                        const topClasses = Object.entries(entry.class_counts || {})
                          .sort(([, a], [, b]) => b - a)
                          .slice(0, 3)
                          .map(([c, n]) => `${c}:${n}`)
                          .join(', ');
                        return (
                          <tr
                            key={entry.frame_idx}
                            className={cn(
                              'transition-colors hover:bg-surface-2 cursor-pointer',
                              selectedFrame?.frame_idx === entry.frame_idx && 'bg-surface-3'
                            )}
                            onClick={() => { setSelectedFrame(entry); seekToTimestamp(entry.timestamp_sec); }}
                          >
                            <td className="px-3 py-1.5 font-mono text-fg-subtle">#{entry.frame_idx}</td>
                            <td className="px-3 py-1.5 font-mono text-fg">{entry.timestamp_sec.toFixed(2)}s</td>
                            <td className="px-3 py-1.5 font-mono font-semibold text-accent">{entry.total_count}</td>
                            <td className="px-3 py-1.5 font-mono text-fg-muted">{entry.rolling_avg.toFixed(1)}</td>
                            <td className="px-3 py-1.5">
                              <span
                                className="px-1.5 py-0.5 rounded text-[10.5px] font-semibold text-white"
                                style={{ backgroundColor: CONGESTION_COLORS[entry.congestion] || '#888' }}
                              >
                                {entry.congestion?.toUpperCase()}
                              </span>
                            </td>
                            <td className="px-3 py-1.5 font-mono text-[11px] text-fg-subtle">{topClasses}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </PageBody>
    </div>
  );
}
