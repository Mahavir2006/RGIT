// The agent floor: a 3D operations kitchen where each desk is a specialist agent and the
// bots walk to a desk when real work lands on them.
//
// Structure follows the reference implementation in
// C:\Users\Omkar Kudalkar\OneDrive\Desktop\serp-api\frontend\src\components\Kitchen.jsx
// (floor, desks with live monitors, lounge -> desk walk cycle, work packets along
// workflow edges, wall board, hover/click inspection). What changed:
//
//   * the roster is Urban Sentinel's agent set rather than a job-search pipeline;
//   * state is derived from the seeded scenario dataset, not from an SSE socket, so the
//     floor renders deterministically and offline;
//   * every colour resolves to a console design token, so the floor follows the theme
//     instead of carrying its own hard-coded palette.
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useTheme } from '@/lib/theme.jsx';
import { AGENTS, AGENT_IDS, AGENT_META, AGENT_LAYOUT, UPSTREAM } from '@/lib/agents.js';

export { AGENT_META, AGENT_LAYOUT };

function textTexture(width, height, draw) {
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  draw(canvas.getContext('2d'), width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.anisotropy = 4;
  return texture;
}

export default function KitchenFloor({ snap, onSelect, selected, apiRef }) {
  const mount = useRef(null);
  const api = useRef({});
  api.current.snap = snap;
  const { theme } = useTheme();

  useEffect(() => {
    const host = mount.current;
    if (!host) return undefined;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      host.innerHTML = '<div class="grid h-full place-items-center px-6 text-center text-[13px] text-fg-muted">3D floor unavailable. The agent list below carries the same live state.</div>';
      return undefined;
    }

    // Tokens drive the whole scene so the floor matches the active theme.
    const styles = getComputedStyle(document.documentElement);
    const css = name => styles.getPropertyValue(name).trim() || '#888888';
    const INK = css('--fg');
    const PAPER = css('--surface');
    // The floor must be a different tone from the desks, otherwise in a light theme the
    // desks vanish into it and only their outlines survive.
    const FLOOR = css('--surface-3');
    const SHADOW = css('--border-strong');
    const ACCENT = css('--accent');
    const HEALTHY = css('--healthy');
    const DEGRADED = css('--degraded');
    const CRITICAL = css('--critical');
    const BORDER = css('--border');
    const STATUS_COLOUR = { idle: BORDER, working: ACCENT, waiting: DEGRADED, attention: CRITICAL, complete: HEALTHY };

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, host.clientWidth < 640 ? 1.25 : 1.75));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.setClearAlpha(0);
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(46, host.clientWidth / host.clientHeight, 0.1, 200);
    camera.position.set(0, 13, 15);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.5, 0);
    controls.enablePan = false;
    controls.minDistance = 8;
    controls.maxDistance = 30;
    controls.maxPolarAngle = 1.38;
    controls.enableDamping = true;

    scene.add(new THREE.HemisphereLight(0xffffff, FLOOR, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(6, 12, 8);
    scene.add(key);

    // The silhouette is carried by edges, which resolve to --fg: near-black in light theme and
// near-white in dark. That guarantees desks read in both themes regardless of surface tone.
    const inkMaterial = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.7 });
    // Desks sit a step brighter than the floor so the object never dissolves into it.
    const paperMaterial = new THREE.MeshStandardMaterial({ color: PAPER, roughness: 0.85 });
    const outline = mesh => {
      mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), inkMaterial));
      return mesh;
    };

    // Floor and entrance sign.
    const floor = new THREE.Mesh(new THREE.BoxGeometry(24, 0.3, 17), new THREE.MeshStandardMaterial({ color: FLOOR, roughness: 1 }));
    floor.position.y = -0.15;
    scene.add(floor);
    const grid = new THREE.GridHelper(24, 24, INK, INK);
    grid.material.transparent = true;
    grid.material.opacity = 0.1;
    grid.position.y = 0.01;
    scene.add(grid);

    const signTexture = textTexture(1024, 128, (ctx) => {
      ctx.fillStyle = INK; ctx.fillRect(0, 0, 1024, 128);
      ctx.fillStyle = PAPER;
      ctx.font = '600 44px "NB Architekt", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('URBAN SENTINEL — AGENT FLOOR', 512, 58);
      ctx.fillStyle = ACCENT;
      ctx.font = '400 24px "NB Architekt", sans-serif';
      ctx.fillText('EVERY DESK BELOW IS A REAL AGENT · SELECT ONE TO INSPECT', 512, 100);
    });
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(10, 1.25), new THREE.MeshBasicMaterial({ map: signTexture, transparent: true }));
    sign.position.set(0, 1.1, 8.2);
    sign.rotation.y = Math.PI;
    scene.add(sign);

    // Wall board: the shared operational state, readable from across the floor.
    const wallTexture = textTexture(1024, 576, () => { });
    const wallMesh = new THREE.Mesh(new THREE.PlaneGeometry(9, 5.06), new THREE.MeshBasicMaterial({ map: wallTexture }));
    wallMesh.position.set(0, 3.4, -8.2);
    const wallFrame = outline(new THREE.Mesh(new THREE.BoxGeometry(9.4, 5.46, 0.18), paperMaterial));
    wallFrame.position.set(0, 3.4, -8.32);
    scene.add(wallFrame, wallMesh);
    let wallKey = '';

    // Hub = orchestrator. Control plane, never a researcher.
    const hub = new THREE.Group();
    const hubBase = outline(new THREE.Mesh(new THREE.BoxGeometry(3.4, 1.0, 2.4), paperMaterial));
    hubBase.position.y = 0.5;
    hubBase.userData.aid = 'hub';
    const hubContact = new THREE.Mesh(new THREE.CircleGeometry(2.3, 40).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: SHADOW, transparent: true, opacity: 0.18, depthWrite: false }));
    hubContact.position.y = 0.012;
    const hubTop = new THREE.Mesh(new THREE.BoxGeometry(3.6, 0.12, 2.6), new THREE.MeshStandardMaterial({ color: INK, roughness: 0.6 }));
    hubTop.position.y = 1.06;
    const hubDot = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 12), new THREE.MeshBasicMaterial({ color: BORDER }));
    hubDot.position.y = 1.7;
    hub.add(hubContact, hubBase, hubTop, hubDot);
    const hubLabel = new THREE.Sprite(new THREE.SpriteMaterial({
      map: textTexture(512, 128, ctx => {
        ctx.fillStyle = INK; ctx.font = '600 40px "NB Architekt", sans-serif'; ctx.textAlign = 'center';
        ctx.fillText('ORCHESTRATOR', 256, 50);
        ctx.fillStyle = css('--fg-muted'); ctx.font = '400 22px "NB Architekt", sans-serif';
        ctx.fillText('routes work · holds the approval gate', 256, 92);
      }),
      transparent: true, depthWrite: false
    }));
    hubLabel.scale.set(3.4, 0.85, 1);
    hubLabel.position.y = 2.6;
    hub.add(hubLabel);
    hub.position.set(0, 0, 3.4);
    hub.userData.aid = 'hub';
    hub.userData.pos = new THREE.Vector3(0, 1.6, 3.4);
    scene.add(hub);

    // Desks.
    const desks = {};
    const hitboxes = [];
    for (const id of AGENT_IDS) {
      const [x, z] = AGENT_LAYOUT[id];
      const group = new THREE.Group();
      group.position.set(x, 0, z);

      const top = outline(new THREE.Mesh(new THREE.BoxGeometry(2.3, 0.12, 1.3), paperMaterial));
      top.position.y = 0.78;
      const body = outline(new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.72, 1.0), paperMaterial));
      body.position.y = 0.36;
      const stand = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.5, 0.1), new THREE.MeshStandardMaterial({ color: INK, roughness: 0.6 }));
      stand.position.set(0, 1.1, -0.35);
      const shell = outline(new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.85, 0.08), paperMaterial));
      shell.position.set(0, 1.65, -0.35);
      const screenTexture = textTexture(256, 160, () => { });
      const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.22, 0.72), new THREE.MeshBasicMaterial({ map: screenTexture }));
      screen.position.set(0, 1.65, -0.3);

      // Contact shadow so the desk is anchored to the floor rather than floating.
      const contact = new THREE.Mesh(new THREE.CircleGeometry(1.5, 32).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: SHADOW, transparent: true, opacity: 0.16, depthWrite: false }));
      contact.position.y = 0.012;

      // One signature prop per agent, so each desk reads as its own workstation.
      const prop = new THREE.Group();
      const propDark = new THREE.MeshStandardMaterial({ color: INK, roughness: 0.7 });
      const addBox = (w, h, d, material, x, y, z, rotationZ = 0) => {
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
        mesh.position.set(x, y, z); mesh.rotation.z = rotationZ;
        prop.add(mesh);
        return mesh;
      };
      if (id === 'ingest') {
        // Antenna dish: the connector pulling signals in.
        const dish = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.16, 14, 1, true), propDark);
        dish.rotation.x = -0.7; dish.position.y = 0.22;
        prop.add(dish);
      } else if (id === 'signal') {
        // Magnifier: reading anomalies in the signal.
        const rim = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.028, 8, 20), propDark);
        rim.position.y = 0.24;
        const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.22, 6), propDark);
        stick.position.set(0.09, 0.08, 0); stick.rotation.z = -0.5;
        prop.add(rim, stick);
      } else if (id === 'validate') {
        // Cube: the deterministic pass/fail gate.
        addBox(0.2, 0.2, 0.2, new THREE.MeshStandardMaterial({ color: HEALTHY, roughness: 0.6 }), 0, 0.14, 0);
      } else if (id === 'fuse') {
        // Two joining blocks: signals merging into one record.
        addBox(0.14, 0.14, 0.14, paperMaterial, -0.12, 0.11, 0);
        addBox(0.14, 0.14, 0.14, new THREE.MeshStandardMaterial({ color: ACCENT }), 0.12, 0.11, 0);
      } else if (id === 'causal') {
        // Stacked cards: competing hypotheses.
        for (let k = 0; k < 3; k++) addBox(0.3, 0.025, 0.4, paperMaterial, (k - 1) * 0.02, 0.05 + k * 0.035, 0, (k - 1) * 0.06);
      } else if (id === 'respond') {
        // Leaning placard: a recommendation held for review.
        addBox(0.34, 0.22, 0.03, paperMaterial, 0, 0.15, 0, -0.12);
      } else if (id === 'provenance') {
        addBox(0.26, 0.02, 0.34, paperMaterial, 0, 0.06, 0);
        addBox(0.26, 0.02, 0.34, new THREE.MeshStandardMaterial({ color: ACCENT, transparent: true, opacity: 0.7 }), 0, 0.09, 0);
      } else {
        // Beacon: source health.
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.42, 6), propDark);
        pole.position.y = 0.25;
        const tip = new THREE.Mesh(new THREE.SphereGeometry(0.05, 10, 8), new THREE.MeshBasicMaterial({ color: DEGRADED }));
        tip.position.y = 0.48;
        prop.add(pole, tip);
      }
      prop.position.set(-0.62, 1.0, 0.1);

      const chair = new THREE.Group();
      const seat = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.09, 14), new THREE.MeshStandardMaterial({ color: INK, roughness: 0.7 }));
      seat.position.y = 0.45;
      const back = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.42, 0.07), new THREE.MeshStandardMaterial({ color: INK, roughness: 0.7 }));
      back.position.set(0, 0.72, -0.2);
      chair.add(seat, back);
      chair.position.set(0, 0, 1.55);
      chair.rotation.y = Math.PI;

      const plate = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.42), new THREE.MeshBasicMaterial({
        map: textTexture(320, 84, ctx => {
          ctx.fillStyle = PAPER; ctx.fillRect(0, 0, 320, 84);
          ctx.strokeStyle = INK; ctx.lineWidth = 4; ctx.strokeRect(3, 3, 314, 78);
          ctx.fillStyle = INK; ctx.font = '600 26px "NB Architekt", sans-serif'; ctx.textAlign = 'center';
          ctx.fillText(AGENT_META[id].name.toUpperCase(), 160, 52);
        }),
        transparent: true
      }));
      plate.position.set(0, 0.42, 0.66);

      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.11, 12, 10), new THREE.MeshBasicMaterial({ color: BORDER }));
      dot.position.set(-1.0, 1.0, 0.4);
      const bubble = new THREE.Sprite(new THREE.SpriteMaterial({ map: textTexture(512, 128, () => { }), transparent: true, depthWrite: false }));
      bubble.scale.set(2.6, 0.65, 1);
      bubble.position.set(0, 2.75, 0);
      bubble.visible = false;
      const halo = new THREE.Mesh(new THREE.TorusGeometry(1.35, 0.035, 8, 48),
        new THREE.MeshBasicMaterial({ color: BORDER, transparent: true, opacity: 0.45 }));
      halo.rotation.x = Math.PI / 2;
      halo.position.y = 0.03;

      const hit = new THREE.Mesh(new THREE.BoxGeometry(2.6, 3.1, 2.2), new THREE.MeshBasicMaterial({ visible: false }));
      hit.position.y = 1.4;
      hit.userData.aid = id;

      group.add(top, body, stand, shell, screen, prop, contact, plate, dot, bubble, halo, hit, chair);
      group.rotation.y = z < 0 ? 0 : Math.PI;
      scene.add(group);
      hitboxes.push(hit);
      desks[id] = {
        group, screenTexture, bubble, dot, halo, screenKey: '', bubbleKey: '', x, z,
        chairPos: new THREE.Vector3(x, 0, z + (z < 0 ? 1.55 : -1.55))
      };
    }

    // Bots: lounge behind the hub, walk to a desk when work lands.
    const ACCENTS = {
      ingest: ACCENT, signal: ACCENT, validate: BORDER, fuse: ACCENT,
      causal: ACCENT, respond: DEGRADED, provenance: BORDER, monitor: DEGRADED
    };
    const inkBody = new THREE.MeshStandardMaterial({ color: INK, roughness: 0.65 });
    const bodyLight = new THREE.MeshStandardMaterial({ color: PAPER, roughness: 0.8 });
    const lounge = AGENT_IDS.map((_, index) => new THREE.Vector3(-4.2 + index * 1.2, 0, 6.6));

    const bots = AGENT_IDS.map((id, index) => {
      const accentMaterial = new THREE.MeshBasicMaterial({ color: ACCENTS[id] });
      const group = new THREE.Group();
      const legGeometry = new THREE.BoxGeometry(0.11, 0.34, 0.11);
      legGeometry.translate(0, -0.17, 0);
      const legL = new THREE.Mesh(legGeometry, inkBody); legL.position.set(-0.1, 0.34, 0);
      const legR = new THREE.Mesh(legGeometry, inkBody); legR.position.set(0.1, 0.34, 0);
      const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.26, 6, 12), inkBody);
      torso.position.y = 0.62;
      const badge = new THREE.Mesh(new THREE.CircleGeometry(0.06, 12), accentMaterial);
      badge.position.set(0, 0.66, 0.215);
      const headGroup = new THREE.Group(); headGroup.position.y = 1.02;
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 12), bodyLight);
      const visor = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.09, 0.06), accentMaterial);
      visor.position.set(0, 0.02, 0.14);
      headGroup.add(head, visor);
      const armGeometry = new THREE.BoxGeometry(0.09, 0.3, 0.09);
      armGeometry.translate(0, -0.15, 0);
      const armL = new THREE.Mesh(armGeometry, inkBody); armL.position.set(-0.28, 0.74, 0);
      const armR = new THREE.Mesh(armGeometry, inkBody); armR.position.set(0.28, 0.74, 0);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.03, 8, 24),
        new THREE.MeshBasicMaterial({ color: BORDER, transparent: true, opacity: 0.6 }));
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 0.03;
      group.add(legL, legR, torso, badge, headGroup, armL, armR, ring);

      const stool = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.09, 14),
        new THREE.MeshStandardMaterial({ color: INK, roughness: 0.7 }));
      stool.position.set(lounge[index].x, 0.42, lounge[index].z);
      scene.add(stool);
      group.position.copy(lounge[index]);
      group.rotation.y = Math.PI;
      scene.add(group);
      return { id, group, legL, legR, torso, headGroup, armL, armR, ring, home: lounge[index].clone(), seed: index * 1.7, pointing: 0, pointTimer: 3 };
    });

    // Work packets travelling along workflow edges.
    const packetGeometry = new THREE.SphereGeometry(0.11, 10, 8);
    const packetMaterial = new THREE.MeshBasicMaterial({ color: ACCENT });
    const packets = Array.from({ length: 8 }, () => {
      const mesh = new THREE.Mesh(packetGeometry, packetMaterial);
      mesh.visible = false;
      scene.add(mesh);
      return { mesh, on: false, from: new THREE.Vector3(), to: new THREE.Vector3(), t: 0 };
    });
    const seenPackets = new Set();
    const positionOf = id => (id === 'hub'
      ? hub.userData.pos
      : new THREE.Vector3(desks[id].x, 1.5, desks[id].z));

    function drawScreen(id, state) {
      const desk = desks[id];
      const head = (state.tool || state.status || 'working').slice(0, 26);
      const body = String(state.summary || state.task || '').slice(0, 44);
      const key = `${head}|${body}`;
      if (desk.screenKey === key) return;
      desk.screenKey = key;
      const ctx = desk.screenTexture.image.getContext('2d');
      ctx.fillStyle = INK; ctx.fillRect(0, 0, 256, 160);
      ctx.fillStyle = ACCENT; ctx.font = '600 20px "NB Architekt", sans-serif';
      ctx.fillText(head.toUpperCase(), 12, 34);
      ctx.fillStyle = css('--fg-muted'); ctx.font = '400 14px "NB Architekt", sans-serif';
      let line = '', y = 62;
      for (const word of body.split(' ')) {
        if ((line + ' ' + word).length > 28) { ctx.fillText(line, 12, y); y += 20; line = word; if (y > 140) break; }
        else line = line ? `${line} ${word}` : word;
      }
      if (line && y <= 140) ctx.fillText(line, 12, y);
      desk.screenTexture.needsUpdate = true;
    }

    function drawBubble(id, text) {
      const desk = desks[id];
      if (desk.bubbleKey === text) return;
      desk.bubbleKey = text;
      const texture = desk.bubble.material.map;
      const ctx = texture.image.getContext('2d');
      ctx.clearRect(0, 0, 512, 128);
      ctx.fillStyle = PAPER;
      ctx.strokeStyle = INK; ctx.lineWidth = 4;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(4, 4, 504, 92, 16); else ctx.rect(4, 4, 504, 92);
      ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(232, 96); ctx.lineTo(256, 122); ctx.lineTo(280, 96); ctx.closePath();
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = INK; ctx.font = '400 24px "NB Architekt", sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(text.length > 44 ? `${text.slice(0, 43)}…` : text, 256, 60);
      texture.needsUpdate = true;
    }

    function drawWall(data) {
      const key = JSON.stringify([data.task, data.phase, data.pending, data.mode]);
      if (wallKey === key) return;
      wallKey = key;
      const ctx = wallTexture.image.getContext('2d');
      ctx.fillStyle = PAPER; ctx.fillRect(0, 0, 1024, 576);
      ctx.fillStyle = INK; ctx.font = '600 38px "NB Architekt", sans-serif'; ctx.textAlign = 'left';
      ctx.fillText('URBAN SENTINEL', 48, 62);
      ctx.fillStyle = ACCENT; ctx.font = '400 24px "NB Architekt", sans-serif';
      ctx.fillText(data.mode === 'sim' ? 'SIMULATED REPLAY — no live provider data' : 'LIVE — real agent events', 48, 100);
      ctx.fillStyle = INK; ctx.font = '400 25px "NB Architekt", sans-serif';
      const task = (data.task || '').slice(0, 66);
      ctx.fillText(`SCENARIO: ${task}`, 48, 148);
      AGENT_IDS.forEach((id, index) => {
        const y = 200 + index * 38;
        const state = data.phase?.[id] || '○';
        ctx.fillStyle = state === '✓' ? HEALTHY : state === '●' ? ACCENT : state === '⚠' ? CRITICAL : BORDER;
        ctx.font = '400 24px "NB Architekt", sans-serif';
        ctx.fillText(state, 48, y);
        ctx.fillStyle = INK;
        ctx.fillText(AGENT_META[id].name.toUpperCase(), 96, y);
      });
      ctx.fillStyle = INK; ctx.font = '400 24px "NB Architekt", sans-serif';
      ctx.fillText(`EVENTS  ${data.events ?? 0}`, 600, 220);
      ctx.fillStyle = DEGRADED;
      ctx.fillText(`AWAITING APPROVAL  ${data.pending ?? 0}`, 600, 270);
      ctx.fillStyle = css('--fg-muted');
      ctx.fillText('Nothing dispatches without a human decision.', 600, 320);
      ctx.fillStyle = ACCENT;
      ctx.fillRect(600, 360, 300, 6);
      wallTexture.needsUpdate = true;
    }

    // Hover and selection.
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2(-10, -10);
    let hovered = null;
    let downAt = null;

    const onMove = event => {
      const rect = host.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      api.current.hover = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const onDown = event => { downAt = [event.clientX, event.clientY]; };
    const onUp = event => {
      if (!downAt) return;
      const dx = event.clientX - downAt[0], dy = event.clientY - downAt[1];
      downAt = null;
      if (dx * dx + dy * dy > 36 || !hovered) return;
      api.current.onSelect?.(hovered === 'hub' ? 'orchestrator' : hovered);
    };

    host.addEventListener('pointermove', onMove);
    host.addEventListener('pointerdown', onDown);
    host.addEventListener('pointerup', onUp);

    const clock = new THREE.Clock();
    let frame = 0;
    let alive = true;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const cameraGoal = { on: false, position: new THREE.Vector3(), target: new THREE.Vector3() };

    api.current.focusOn = point => {
      cameraGoal.on = true;
      cameraGoal.target.copy(point);
      cameraGoal.position.set(point.x * 0.6, 7, point.z * 0.6 + 8);
    };

    const faceToward = (bot, x, z) => { bot.group.rotation.y = Math.atan2(x - bot.group.position.x, z - bot.group.position.z); };
    const setPose = (bot, pose, t) => {
      if (pose === 'sit') {
        bot.legL.rotation.x = -1.5; bot.legR.rotation.x = -1.5;
        bot.torso.position.y = 0.5; bot.headGroup.position.y = 0.9;
        bot.armL.rotation.x = -1 + Math.sin(t * 10 + bot.seed) * 0.26;
        bot.armR.rotation.x = -1 + Math.sin(t * 10 + bot.seed + 1.2) * 0.26;
      } else if (pose === 'walk') {
        bot.legL.rotation.x = Math.sin(t * 11 + bot.seed) * 0.6;
        bot.legR.rotation.x = -Math.sin(t * 11 + bot.seed) * 0.6;
        bot.torso.position.y = 0.62; bot.headGroup.position.y = 1.02;
        bot.armL.rotation.x = -Math.sin(t * 11 + bot.seed) * 0.4;
        bot.armR.rotation.x = Math.sin(t * 11 + bot.seed) * 0.4;
      } else {
        bot.legL.rotation.x *= 0.8; bot.legR.rotation.x *= 0.8;
        bot.torso.position.y = 0.62; bot.headGroup.position.y = 1.02;
        bot.armL.rotation.x *= 0.85; bot.armR.rotation.x *= 0.85;
      }
    };

    function tick() {
      if (!alive) return;
      frame = requestAnimationFrame(tick);
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;
      const state = api.current.snap || { agents: {} };

      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects([...hitboxes, hubBase], false);
      const next = hits.length ? (hits[0].object.userData.aid || null) : null;
      if (next !== hovered) {
        hovered = next;
        api.current.onHover?.(hovered);
        host.style.cursor = hovered ? 'pointer' : 'default';
      }

      for (const id of AGENT_IDS) {
        const desk = desks[id];
        const agent = state.agents?.[id] || { status: 'idle', task: '' };
        const colour = new THREE.Color(STATUS_COLOUR[agent.status] ?? BORDER);
        desk.dot.material.color.copy(colour);
        desk.halo.material.color.copy(colour);

// The desk is deliberately never scaled or moved. Hover and selection change the halo
        // and status dot only, so a workstation keeps its exact footprint while an agent works.
        const isSelected = selected === id;
        desk.halo.visible = isSelected || hovered === id;

        if (agent.status === 'working') {
          drawScreen(id, agent);
          drawBubble(id, agent.task || 'Working…');
          desk.bubble.visible = true;
        } else {
          desk.bubble.visible = false;
        }
        if (agent.status !== 'idle') drawScreen(id, agent);

        // A packet only spawns the first time a given work item is seen, so replays do
        // not flood the floor with traffic.
        if (agent.packetId && !seenPackets.has(agent.packetId) && !reduced) {
          seenPackets.add(agent.packetId);
          const packet = packets.find(item => !item.on);
          if (packet) {
            packet.on = true; packet.t = 0;
            packet.from.copy(positionOf(agent.from || UPSTREAM[id]));
            packet.to.copy(positionOf(id));
            packet.mesh.visible = true;
          }
        }
      }

      hubDot.material.color.set(STATUS_COLOUR[state.hub || 'idle'] ?? BORDER);

      for (const bot of bots) {
        const agent = state.agents?.[bot.id] || {};
        const status = agent.status || 'idle';
        const desk = desks[bot.id];
        bot.ring.material.color.set(STATUS_COLOUR[status] ?? BORDER);
        const position = bot.group.position;

        if (status === 'working' || status === 'waiting' || status === 'attention') {
          bot.ring.scale.setScalar(status === 'attention' && !reduced ? 1 + Math.sin(t * 6) * 0.12 : 1);
          const target = status === 'attention' ? desk.chairPos : desk.chairPos;
          const dx = target.x - position.x, dz = target.z - position.z;
          const distance = Math.hypot(dx, dz);
          if (distance > 0.3) {
            if (!reduced) {
              const step = Math.min(distance, 2.5 * dt) / (distance || 1);
              position.x += dx * step; position.z += dz * step;
              position.y = Math.abs(Math.sin(t * 9)) * 0.08;
              bot.group.rotation.y = Math.atan2(dx, dz);
              setPose(bot, 'walk', t);
            }
          } else {
            position.y = 0;
            faceToward(bot, desk.x, desk.z);
            setPose(bot, 'sit', t);
            bot.headGroup.rotation.y = Math.sin(t * 1.8 + bot.seed) * 0.25;
            if (!reduced) {
              bot.pointTimer -= dt;
              if (bot.pointTimer <= 0) { bot.pointTimer = 4 + (bot.seed % 3); bot.pointing = 1.2; }
              if (bot.pointing > 0) { bot.pointing -= dt; bot.armR.rotation.x = -2.3; bot.armR.rotation.z = -0.4; }
            }
          }
        } else {
          bot.ring.scale.setScalar(1);
          const dx = bot.home.x - position.x, dz = bot.home.z - position.z;
          const distance = Math.hypot(dx, dz);
          if (distance > 0.3 && !reduced) {
            const step = Math.min(distance, 2.2 * dt) / (distance || 1);
            position.x += dx * step; position.z += dz * step;
            position.y = Math.abs(Math.sin(t * 9)) * 0.08;
            bot.group.rotation.y = Math.atan2(dx, dz);
            setPose(bot, 'walk', t);
          } else {
            position.y = 0;
            bot.group.rotation.y += ((Math.PI - bot.group.rotation.y + Math.PI * 3) % (Math.PI * 2) - Math.PI) * 0.05;
            setPose(bot, 'stand', t);
          }
        }
      }

      for (const packet of packets) {
        if (!packet.on) continue;
        packet.t += dt * 1.1;
        if (packet.t >= 1) { packet.on = false; packet.mesh.visible = false; continue; }
        packet.mesh.position.lerpVectors(packet.from, packet.to, packet.t);
        packet.mesh.position.y += Math.sin(packet.t * Math.PI) * 0.8;
      }

      drawWall(state.wall || {});
      if (cameraGoal.on) {
        camera.position.lerp(cameraGoal.position, 0.06);
        controls.target.lerp(cameraGoal.target, 0.08);
        if (camera.position.distanceTo(cameraGoal.position) < 0.15) cameraGoal.on = false;
      }
      controls.update();
      renderer.render(scene, camera);
    }

    tick();

    const onResize = () => {
      camera.aspect = host.clientWidth / host.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(host.clientWidth, host.clientHeight);
    };
    const observer = new ResizeObserver(onResize);
    observer.observe(host);

    api.current.scene = scene;
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      host.removeEventListener('pointermove', onMove);
      host.removeEventListener('pointerdown', onDown);
      host.removeEventListener('pointerup', onUp);
      controls.dispose();
      scene.traverse(object => {
        object.geometry?.dispose?.();
        if (Array.isArray(object.material)) object.material.forEach(m => m.dispose()); else object.material?.dispose?.();
        object.material?.map?.dispose?.();
      });
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
    };
  }, [theme]);

  useEffect(() => { api.current.onSelect = onSelect; });
  useEffect(() => { if (apiRef) apiRef.current = api.current; }, [apiRef]);

  return <div ref={mount} className="absolute inset-0" aria-label="3D agent operations floor" />;
}