// Step 1 of the flow: a 3D Earth floating inside the real night sky.
// Drag to look around, scroll to zoom, click any point of the sky (or a glowing
// target) to choose the patch SPHEREx should show you.
//
// Stars: the ~5,000 naked-eye stars (d3-celestial data, Yale Bright Star based),
// coloured by their real colour. Lines: the constellation figures.
// Directions use the sky's own coordinates: RA/Dec -> a point on a big sphere
// around the Earth, with Earth's north pole pointing at the north celestial pole.
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/OrbitControls.js";

const R_SKY = 100;
const DEG = Math.PI / 180;

// RA/Dec (degrees) -> unit vector. Seen from inside the sphere, RA increases to
// the left (east) when north is up, exactly like the real sky.
export function radecToVec(ra, dec, r = 1) {
  const a = ra * DEG, d = dec * DEG;
  return new THREE.Vector3(r * Math.cos(d) * Math.cos(a), r * Math.sin(d), -r * Math.cos(d) * Math.sin(a));
}
function vecToRadec(v) {
  const n = v.clone().normalize();
  const dec = Math.asin(Math.max(-1, Math.min(1, n.y))) / DEG;
  let ra = Math.atan2(-n.z, n.x) / DEG;
  if (ra < 0) ra += 360;
  return { ra, dec };
}

// star colour from its B-V colour index (blue-white hot stars ... orange cool ones)
function bvToColor(bv) {
  const t = Math.max(-0.4, Math.min(2.0, isFinite(bv) ? bv : 0.6));
  const stops = [[-0.4, [155, 176, 255]], [0.0, [202, 215, 255]], [0.4, [248, 247, 255]],
    [0.8, [255, 244, 234]], [1.2, [255, 210, 161]], [2.0, [255, 160, 100]]];
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1], [t1, c1] = stops[i], f = (t - t0) / (t1 - t0);
      return c0.map((c, k) => (c + (c1[k] - c) * f) / 255);
    }
  }
  return stops[stops.length - 1][1].map((c) => c / 255);
}

export class SkyPicker {
  constructor(container, { onPick, onTarget, onHover }) {
    this.el = container;
    this.onPick = onPick; this.onTarget = onTarget; this.onHover = onHover;
    this.targets = [];
    this.constellations = [];
    this.clock = new THREE.Clock();
    this.busy = false;

    const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    r.setClearColor(0x02040a);
    container.appendChild(r.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(55, 1, 0.05, 1000);
    this.camera.position.set(1.4, 0.8, 4.3);

    const c = this.controls = new OrbitControls(this.camera, r.domElement);
    c.enableDamping = true; c.dampingFactor = 0.07;
    c.minDistance = 1.7; c.maxDistance = 7; c.enablePan = false;
    c.rotateSpeed = 0.5; c.zoomSpeed = 0.7;
    c.autoRotate = true; c.autoRotateSpeed = 0.35;
    r.domElement.addEventListener("pointerdown", () => { c.autoRotate = false; });

    this.labels = document.createElement("div");
    this.labels.className = "sky-labels";
    container.appendChild(this.labels);

    this.buildEarth();
    this.buildSky();
    this.buildReticle();
    this.bindPointer();
    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.loop();
  }

  // ------------------------------------------------------------ Earth
  buildEarth() {
    const tex = new THREE.TextureLoader();
    const day = tex.load("vendor/sky/earth_atmos_2048.jpg");
    day.colorSpace = THREE.SRGBColorSpace;
    const lights = tex.load("vendor/sky/earth_lights_2048.png");
    const clouds = tex.load("vendor/sky/earth_clouds_1024.png");
    this.sun = new THREE.Vector3(0.55, 0.35, 1).normalize();

    // day side lit by the Sun, city lights glowing on the night side
    const mat = new THREE.ShaderMaterial({
      uniforms: { day: { value: day }, night: { value: lights }, sun: { value: this.sun } },
      vertexShader: `varying vec2 vUv; varying vec3 vN;
        void main(){ vUv=uv; vN=normalize(mat3(modelMatrix)*normal);
        gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
      fragmentShader: `uniform sampler2D day; uniform sampler2D night; uniform vec3 sun;
        varying vec2 vUv; varying vec3 vN;
        void main(){ float l=dot(normalize(vN),sun); float d=smoothstep(-0.15,0.25,l);
          vec3 c=texture2D(day,vUv).rgb*(0.08+1.05*d); vec3 n=texture2D(night,vUv).rgb*vec3(1.0,0.85,0.55)*1.6*(1.0-d);
          gl_FragColor=vec4(c+n,1.0);
          #include <colorspace_fragment>
        } `,
    });
    this.earth = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), mat);
    this.scene.add(this.earth);

    this.clouds = new THREE.Mesh(new THREE.SphereGeometry(1.012, 96, 64),
      new THREE.MeshLambertMaterial({ map: clouds, transparent: true, opacity: 0.55, depthWrite: false }));
    this.scene.add(this.clouds);
    const light = new THREE.DirectionalLight(0xffffff, 2.2);
    light.position.copy(this.sun).multiplyScalar(10);
    this.scene.add(light, new THREE.AmbientLight(0x334466, 0.25));

    // soft blue atmosphere halo
    const halo = new THREE.ShaderMaterial({
      transparent: true, side: THREE.BackSide, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: `varying vec3 vN; varying vec3 vP;
        void main(){ vN=normalize(normalMatrix*normal); vec4 p=modelViewMatrix*vec4(position,1.0); vP=p.xyz;
        gl_Position=projectionMatrix*p;} `,
      fragmentShader: `varying vec3 vN; varying vec3 vP;
        void main(){ float f=pow(0.75-dot(vN,normalize(-vP))*-1.0,3.0);
        gl_FragColor=vec4(0.35,0.62,1.0,1.0)*clamp(f,0.0,1.0)*0.9;} `,
    });
    this.scene.add(new THREE.Mesh(new THREE.SphereGeometry(1.18, 64, 48), halo));

    // the SPHEREx telescope's orbit: a thin ring passing over the poles
    const orbit = new THREE.Mesh(new THREE.TorusGeometry(1.35, 0.0035, 8, 200),
      new THREE.MeshBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.55 }));
    orbit.rotation.y = 0.6;
    this.orbit = orbit;
    this.scene.add(orbit);
    this.sat = new THREE.Mesh(new THREE.SphereGeometry(0.022, 16, 12), new THREE.MeshBasicMaterial({ color: 0xbfe0ff }));
    this.scene.add(this.sat);
  }

  // ------------------------------------------------------------ stars and constellations
  async buildSky() {
    // invisible sphere that catches clicks on the sky
    this.skySphere = new THREE.Mesh(new THREE.SphereGeometry(R_SKY, 64, 32),
      new THREE.MeshBasicMaterial({ side: THREE.BackSide, visible: false }));
    this.scene.add(this.skySphere);

    // faint background dust of very faint stars (decoration, random)
    const dust = new Float32Array(9000 * 3);
    for (let i = 0; i < 9000; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(R_SKY * 1.02);
      dust.set([v.x, v.y, v.z], i * 3);
    }
    const dg = new THREE.BufferGeometry();
    dg.setAttribute("position", new THREE.BufferAttribute(dust, 3));
    this.scene.add(new THREE.Points(dg, new THREE.PointsMaterial({ color: 0x8090b0, size: 0.18, sizeAttenuation: true, transparent: true, opacity: 0.5 })));

    const [stars, lines, names] = await Promise.all(
      ["stars.6.json", "constellations.lines.json", "constellations.json"].map((f) => fetch("vendor/sky/" + f).then((r) => r.json())));

    const pos = [], col = [], size = [];
    for (const f of stars.features) {
      const [lon, lat] = f.geometry.coordinates;
      const m = f.properties.mag;
      const v = radecToVec((lon + 360) % 360, lat, R_SKY);
      pos.push(v.x, v.y, v.z);
      col.push(...bvToColor(parseFloat(f.properties.bv)));
      size.push(Math.max(0.9, 7.0 - 1.0 * m));
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
    g.setAttribute("size", new THREE.Float32BufferAttribute(size, 1));
    const starMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, vertexColors: true,
      uniforms: { scale: { value: 1 }, time: { value: 0 } },
      vertexShader: `attribute float size; varying vec3 vC; uniform float scale; uniform float time;
        void main(){ vC=color; vec4 p=modelViewMatrix*vec4(position,1.0);
          float tw = 0.85 + 0.15*sin(time*2.0 + position.x*3.1 + position.y*1.7);
          gl_PointSize = size*scale*tw; gl_Position=projectionMatrix*p; }`,
      fragmentShader: `varying vec3 vC;
        void main(){ vec2 d=gl_PointCoord-0.5; float r=length(d); float a=smoothstep(0.5,0.0,r);
          gl_FragColor=vec4(vC*1.25, a); }`,
    });
    this.starMat = starMat;
    this.scene.add(new THREE.Points(g, starMat));

    // constellation stick figures
    const seg = [];
    for (const f of lines.features) {
      for (const line of f.geometry.coordinates) {
        for (let i = 1; i < line.length; i++) {
          const a = radecToVec((line[i - 1][0] + 360) % 360, line[i - 1][1], R_SKY * 0.995);
          const b = radecToVec((line[i][0] + 360) % 360, line[i][1], R_SKY * 0.995);
          seg.push(a.x, a.y, a.z, b.x, b.y, b.z);
        }
      }
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
    this.scene.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x4a6fa5, transparent: true, opacity: 0.35 })));

    // constellation names (used for "this patch is in ...")
    this.constellations = names.features.map((f) => {
      const [lon, lat] = f.geometry.coordinates;
      return { name: f.properties.name, rank: +f.properties.rank, v: radecToVec((lon + 360) % 360, lat) };
    });
    this.constellationLabels = this.constellations.filter((c) => c.rank === 1).map((c) => {
      const el = document.createElement("div");
      el.className = "sky-const"; el.textContent = c.name;
      this.labels.appendChild(el);
      return { el, v: c.v.clone().multiplyScalar(R_SKY) };
    });
  }

  constellationOf(ra, dec) {
    if (!this.constellations.length) return "";
    const v = radecToVec(ra, dec);
    let best = null;
    for (const c of this.constellations) {
      const d = v.angleTo(c.v);
      if (!best || d < best.d) best = { d, name: c.name };
    }
    return best ? best.name : "";
  }

  // ------------------------------------------------------------ tour targets
  setTargets(list) {
    for (const t of this.targets) { this.scene.remove(t.mesh); t.el.remove(); }
    this.targets = list.filter((t) => t.ra !== undefined).map((t) => {
      const v = radecToVec(t.ra, t.dec, R_SKY * 0.98);
      const mesh = new THREE.Mesh(new THREE.RingGeometry(1.4, 1.9, 48),
        new THREE.MeshBasicMaterial({ color: 0xffc857, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
      mesh.position.copy(v); mesh.lookAt(0, 0, 0);
      this.scene.add(mesh);
      const el = document.createElement("button");
      el.className = "sky-target";
      el.innerHTML = `<b>${t.name}</b><span>${t.kind}</span>`;
      el.onclick = (e) => { e.stopPropagation(); this.select(t.ra, t.dec, t); };
      this.labels.appendChild(el);
      return { t, v, mesh, el };
    });
  }

  // ------------------------------------------------------------ choosing a point
  buildReticle() {
    const grp = new THREE.Group();
    const ring = new THREE.Mesh(new THREE.RingGeometry(2.2, 2.6, 64),
      new THREE.MeshBasicMaterial({ color: 0x7ee0ff, transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthWrite: false }));
    const ticks = [];
    for (let k = 0; k < 4; k++) {
      const t = new THREE.Mesh(new THREE.PlaneGeometry(0.25, 1.6),
        new THREE.MeshBasicMaterial({ color: 0x7ee0ff, side: THREE.DoubleSide, depthWrite: false }));
      const a = k * Math.PI / 2;
      t.position.set(Math.cos(a) * 3.4, Math.sin(a) * 3.4, 0);
      t.rotation.z = a + Math.PI / 2;
      ticks.push(t);
    }
    grp.add(ring, ...ticks);
    grp.visible = false;
    this.reticle = grp;
    this.scene.add(grp);
  }

  select(ra, dec, target = null, turn = true) {
    const v = radecToVec(ra, dec, R_SKY * 0.97);
    this.reticle.position.copy(v);
    this.reticle.lookAt(0, 0, 0);
    this.reticle.visible = true;
    this.picked = { ra, dec, target };
    this.controls.autoRotate = false;
    if (turn) this.turnToward(ra, dec);
    this.onPick && this.onPick({ ra, dec, target, constellation: this.constellationOf(ra, dec) });
  }

  // swing the camera round so the chosen point is in view, just beside the Earth
  turnToward(ra, dec, ms = 1200) {
    const d = radecToVec(ra, dec);
    const side = new THREE.Vector3().crossVectors(d, new THREE.Vector3(0, 1, 0));
    if (side.lengthSq() < 1e-6) side.set(1, 0, 0);
    side.normalize();
    // stand behind the Earth (opposite the target), a little to one side
    // (offsets chosen so the point shows up upper-right of the Earth, clear of the side panels)
    const upv = new THREE.Vector3().crossVectors(side, d).normalize();
    const end = d.clone().multiplyScalar(-1).addScaledVector(side, 0.22).addScaledVector(upv, 0.55).normalize()
      .multiplyScalar(this.camera.position.length());
    const start = this.camera.position.clone();
    const t0 = performance.now();
    const step = () => {
      const f = Math.min(1, (performance.now() - t0) / ms), e = 1 - Math.pow(1 - f, 3);
      // move along the sphere, not through the Earth
      const p = start.clone().normalize().lerp(end.clone().normalize(), e).normalize().multiplyScalar(start.length());
      this.camera.position.copy(p);
      this.controls.update();
      if (f < 1 && !this.busy) requestAnimationFrame(step);
    };
    step();
  }

  bindPointer() {
    const el = this.renderer.domElement;
    const ray = new THREE.Raycaster(), m = new THREE.Vector2();
    let down = null;
    const hit = (e) => {
      const r = el.getBoundingClientRect();
      m.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(m, this.camera);
      if (ray.intersectObject(this.earth).length) return null;   // clicked the Earth, not the sky
      const h = this.skySphere && ray.intersectObject(this.skySphere)[0];
      return h ? vecToRadec(h.point) : null;
    };
    el.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener("pointerup", (e) => {
      if (!down || this.busy) return;
      const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
      down = null;
      if (moved > 6) return;                       // that was a drag, not a click
      const p = hit(e);
      if (p) this.select(p.ra, p.dec, null, false);   // it's already in view: don't swing the camera
    });
    el.addEventListener("pointermove", (e) => {
      const p = hit(e);
      this.onHover && this.onHover(p ? { ...p, constellation: this.constellationOf(p.ra, p.dec) } : null);
      el.style.cursor = p ? "crosshair" : "grab";
    });
  }

  // ------------------------------------------------------------ fly into the chosen patch
  // Two moves blended together: (1) orbit round the Earth to stand beside it, with the
  // patch off to the side so the Earth is out of the way; (2) turn to face the patch and
  // zoom in like a telescope (the field of view narrows from 55 to about 2 degrees).
  flyTo(ra, dec, ms = 2400) {
    this.busy = true;
    this.controls.enabled = false;
    this.controls.autoRotate = false;
    const dir = radecToVec(ra, dec);
    const start = this.camera.position.clone();
    const R = Math.max(start.length(), 3.2);
    let side = start.clone().sub(dir.clone().multiplyScalar(start.dot(dir)));
    if (side.lengthSq() < 1e-4) side = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
    side.normalize();
    const end = side.clone().multiplyScalar(0.97).addScaledVector(dir, -0.22).normalize().multiplyScalar(R);
    const target = dir.clone().multiplyScalar(R_SKY);
    const fov0 = this.camera.fov, fov1 = 2.2;
    const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
    const t0 = performance.now();
    return new Promise((resolve) => {
      const step = () => {
        const f = Math.min(1, (performance.now() - t0) / ms);
        const move = smooth(0, 0.55, f);                 // orbiting
        const turn = smooth(0.1, 0.6, f);                // turning to face the patch
        const zoom = smooth(0.45, 1, f);                 // telescope zoom
        const p = start.clone().normalize().lerp(end.clone().normalize(), move).normalize()
          .multiplyScalar(start.length() + (R - start.length()) * move);
        this.camera.position.copy(p);
        this.camera.lookAt(new THREE.Vector3().lerp(target, turn));
        this.camera.fov = fov0 * Math.pow(fov1 / fov0, zoom);
        this.camera.updateProjectionMatrix();
        this.reticle.scale.setScalar(this.camera.fov / fov0);   // the ring keeps its size on screen while we zoom
        if (f < 1) requestAnimationFrame(step); else resolve();
      };
      step();
    });
  }

  reset() {
    this.reticle.scale.setScalar(1);
    this.camera.fov = 55; this.camera.updateProjectionMatrix();
    this.camera.position.set(1.4, 0.8, 4.3);
    this.controls.target.set(0, 0, 0);
    this.controls.enabled = true;
    this.controls.update();
    this.busy = false;
  }

  // ------------------------------------------------------------ frame loop
  resize() {
    const w = this.el.clientWidth || window.innerWidth, h = this.el.clientHeight || window.innerHeight;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  project(v, el, offset = 0) {
    const p = v.clone().project(this.camera);
    const vis = p.z < 1 && Math.abs(p.x) < 1.1 && Math.abs(p.y) < 1.1;
    if (!vis) { el.style.display = "none"; return; }
    const w = this.renderer.domElement.clientWidth, h = this.renderer.domElement.clientHeight;
    el.style.display = "";
    el.style.transform = `translate(${(p.x + 1) / 2 * w}px, ${(1 - p.y) / 2 * h + offset}px)`;
  }

  loop() {
    requestAnimationFrame(() => this.loop());
    if (document.hidden || this.el.offsetParent === null) return;   // picker not on screen: rest
    const dt = this.clock.getDelta(), t = this.clock.elapsedTime;
    this.earth.rotation.y += dt * 0.05;
    this.clouds.rotation.y += dt * 0.062;
    const a = t * 0.35;
    this.sat.position.set(Math.cos(a) * 1.35, Math.sin(a) * 1.35, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), 0.6);
    if (this.starMat) {
      this.starMat.uniforms.time.value = t;
      this.starMat.uniforms.scale.value = this.renderer.getPixelRatio() * (55 / this.camera.fov) ** 0.6;
    }
    const pulse = 1 + 0.25 * Math.sin(t * 3);
    for (const k of this.targets) {
      k.mesh.scale.setScalar(pulse * this.camera.fov / 55);   // same size on screen while zooming
      this.project(k.v, k.el, 14);
    }
    for (const c of this.constellationLabels || []) this.project(c.v, c.el);
    if (!this.busy) this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
