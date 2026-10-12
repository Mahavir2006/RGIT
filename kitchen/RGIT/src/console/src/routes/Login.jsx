import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import * as THREE from 'three';
import { ArrowRight, Check, Eye } from 'lucide-react';
import { Button, Badge, Input } from '@/components/ui';
import { SentinelMark } from '@/components/brand.jsx';
import { useApp, ROLES } from '@/lib/store.jsx';
import { useTheme } from '@/lib/theme.jsx';
import { ASSETS, project } from '@/data/geo.js';
import { SCENARIO } from '@/data/scenario.js';
import { cn } from '@/lib/utils';

// Quiet ambient radar field. Deliberately low contrast so the form stays the focus.
function RadarField() {
  const mount = useRef(null);
  const { theme } = useTheme();

  useEffect(() => {
    const host = mount.current;
    if (!host) return undefined;
    const styles = getComputedStyle(document.documentElement);
    const hex = name => parseInt((styles.getPropertyValue(name).trim() || '#888888').slice(1), 16);
    const accent = hex('--accent'), border = hex('--border'), accentSoft = hex('--accent-soft');

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(accentSoft, 1);
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    camera.position.set(0, 7, 13);
    camera.lookAt(0, 0, 0);

    const rings = new THREE.Group();
    for (let i = 1; i <= 6; i++) {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(i * 1.5, i * 1.5 + 0.02, 96).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: border, transparent: true, opacity: 0.8 })
      );
      ring.position.y = -2 + i * 0.4;
      rings.add(ring);
    }
    scene.add(rings);

    const spokes = new THREE.Group();
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * Math.PI * 2;
      spokes.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(Math.cos(angle) * 9, 0, Math.sin(angle) * 9)]),
        new THREE.LineBasicMaterial({ color: border, transparent: true, opacity: 0.7 })
      ));
    }
    scene.add(spokes);

    const pulses = [];
    const nodes = new THREE.Group();
    for (const asset of ASSETS.slice(0, 11)) {
      const [x, , z] = project(asset);
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.1, 12, 10), new THREE.MeshBasicMaterial({ color: accent }));
      dot.position.set(x * 0.4, -1.6 + ((x + z) % 2), z * 0.4);
      nodes.add(dot);

      const pulse = new THREE.Mesh(
        new THREE.RingGeometry(0.16, 0.2, 24).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.4, side: THREE.DoubleSide })
      );
      pulse.position.copy(dot.position);
      pulse.userData.delay = Math.random() * 3;
      nodes.add(pulse);
      pulses.push(pulse);
    }
    scene.add(nodes);

    const sweep = new THREE.Mesh(
      new THREE.ConeGeometry(3.6, 11, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.05, side: THREE.DoubleSide })
    );
    sweep.rotation.x = -Math.PI / 2;
    sweep.position.y = -1.4;
    scene.add(sweep);

    function resize() {
      const width = host.clientWidth, h = host.clientHeight;
      if (!width || !h) return;
      renderer.setSize(width, h, false);
      camera.aspect = width / h;
      camera.updateProjectionMatrix();
    }
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    let alive = true, frame = 0;
    const clock = new THREE.Clock();
    function tick() {
      if (!alive) return;
      frame = requestAnimationFrame(tick);
      const t = clock.getElapsedTime();
      sweep.rotation.z = -t * 0.55;
      rings.rotation.y = t * 0.04;
      nodes.rotation.y = t * 0.05;
      for (const pulse of pulses) {
        const phase = (t + pulse.userData.delay) % 2.4;
        pulse.scale.setScalar(1 + phase * 2.4);
        pulse.material.opacity = Math.max(0, 0.4 - phase * 0.17);
      }
      renderer.render(scene, camera);
    }
    tick();

    return () => {
      alive = false; cancelAnimationFrame(frame); observer.disconnect(); renderer.dispose();
      scene.traverse(object => { object.geometry?.dispose?.(); object.material?.dispose?.(); });
      host.removeChild(renderer.domElement);
    };
  }, [theme]);

  return <div ref={mount} className="absolute inset-0" />;
}

export default function Login() {
  const { dispatch, role, signedIn } = useApp();
  const navigate = useNavigate();
  const [selected, setSelected] = useState(role.id);
  const [showPassword, setShowPassword] = useState(false);
  const returning = signedIn;

  function submit(event) {
    event.preventDefault();
    dispatch({ type: 'signIn', role: selected });
    navigate('/overview');
  }

  return (
    <div className="grid h-full lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden border-r border-border lg:block">
        <RadarField />
        <div className="absolute inset-0 bg-gradient-to-r from-transparent to-bg" />
        <div className="absolute inset-x-0 bottom-0 p-10">
          <div className="mb-5 flex items-center gap-2.5">
            <SentinelMark size={28} animate className="text-accent" />
            <span className="font-display text-[15px] italic">Urban Sentinel</span>
          </div>
          <h1 className="max-w-[16ch] text-[40px] font-semibold leading-[1.05] tracking-[-0.025em] text-fg">
            Incident fusion for urban operations
          </h1>
          <p className="mt-4 max-w-[52ch] text-[14px] leading-relaxed text-fg-muted">
            Weather, air quality, traffic, water level and citizen signals resolved into one explainable,
            auditable picture — with competing explanations kept visible rather than resolved away.
          </p>
          <p className="mt-5 max-w-[52ch] text-[12.5px] leading-relaxed text-fg-subtle">
            Decision support for human review. This tool does not dispatch, actuate or publish public warnings.
          </p>
        </div>
      </div>

      <div className="flex items-center justify-center p-8">
        <motion.form
          onSubmit={submit}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-[380px] space-y-5"
        >
          <div>
            <h2 className="text-[20px] font-semibold tracking-[-0.01em]">{returning ? 'Switch role' : 'Sign in'}</h2>
            <p className="mt-1 text-[13px] leading-snug text-fg-muted">
              Least privilege is enforced. Write operations are checked on the server, not only hidden here.
            </p>
          </div>

          <div className="space-y-3">
            <div>
              <label htmlFor="user" className="mb-1.5 block text-[12.5px] font-medium text-fg-muted">Account</label>
              <Input id="user" defaultValue="analyst.andheri" autoComplete="username" />
            </div>
            <div>
              <label htmlFor="pass" className="mb-1.5 block text-[12.5px] font-medium text-fg-muted">Password</label>
              <div className="relative">
                <Input id="pass" type={showPassword ? 'text' : 'password'} defaultValue="demo-password"
                  autoComplete="current-password" className="pr-9" aria-describedby="pass-note" />
                <button type="button" onClick={() => setShowPassword(value => !value)}
                  className="absolute right-1 top-1 grid size-6 place-items-center rounded-[5px] text-fg-subtle hover:bg-surface-2 hover:text-fg"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}>
                  <Eye className="size-3.5" />
                </button>
              </div>
              <p id="pass-note" className="mt-1.5 text-[12px] text-fg-subtle">
                Local demo accounts only. No external identity provider is configured.
              </p>
            </div>
          </div>

          <div>
            <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Role</div>
            <div className="space-y-1">
              {Object.values(ROLES).map(option => (
                <button key={option.id} type="button" onClick={() => setSelected(option.id)} aria-pressed={selected === option.id}
                  className={cn(
                    'flex w-full items-start gap-2.5 rounded-[6px] border px-3 py-2 text-left transition-colors',
                    selected === option.id ? 'border-accent/50 bg-accent-soft' : 'border-border hover:border-border-strong'
                  )}>
                  <span className={cn('mt-0.5', selected === option.id ? 'text-accent' : 'text-fg-subtle')}>
                    {selected === option.id ? <Check className="size-3.5" /> : <span className="block size-3.5 rounded-full border border-border-strong" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-fg">{option.label}</span>
                    <span className="mt-0.5 block text-[12px] leading-snug text-fg-subtle">{option.blurb}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          <label className="flex items-start gap-2 text-[12.5px] text-fg-muted">
            <input type="checkbox" defaultChecked className="mt-0.5 accent-[var(--accent)]" />
            Demo mode — restrict all connectors to labelled replay
          </label>

          <Button variant="primary" size="lg" type="submit" className="w-full">
            {returning ? 'Switch role' : 'Enter console'}<ArrowRight />
          </Button>

          <div className="flex items-center gap-2 border-t border-border pt-4 text-[12px] text-fg-subtle">
            <Badge tone="neutral">{SCENARIO.mode}</Badge>
            <span>dataset {SCENARIO.datasetVersion}</span>
          </div>
        </motion.form>
      </div>
    </div>
  );
}