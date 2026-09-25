/* Yapp avatar — dependency-free metaball body with an integrated ring meter. Sized for a 64 px box (56 px body + ring).
   const av = new YappAvatar(canvas, {size:64, state:'idle', hold:false});
   av.setState(name, {level, confidence, hold, direction, commit})  (hold = pin the state; nothing to do with the hotkey)   states: idle listening thinking dictating acting done unsure refused error
   av.commit()  av.setLevel(v)  av.setConfidence(v)  av.setRing('level'|'confidence'|'countdown'|'none', value)  av.setCountdown(fraction|null)
   Colours come from tokens.css (--yapp-accent, --yapp-ring-track, --yapp-avatar-edge, --yapp-scheme) read off the canvas; call av.syncColors() after an appearance change. */
(function (global) {
  'use strict';
  const TAU = Math.PI * 2, NB = 4;
  function toRgb(L, a, b) {
    const l_ = L + 0.3963377774 * a + 0.2158037573 * b, m_ = L - 0.1055613458 * a - 0.0638541728 * b, s_ = L - 0.0894841775 * a - 1.2914855480 * b;
    const l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_;
    const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;
    const f = x => { x = x < 0 ? 0 : x > 1 ? 1 : x; return Math.round(255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055)); };
    return [f(r), f(g), f(bb)];
  }
  const rgba = (c, al) => 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + al + ')';
  const clamp01 = v => Math.max(0, Math.min(1, +v || 0));
  const SPRINGS = { idle: [30, 9], listening: [110, 16], thinking: [150, 20], dictating: [130, 18], acting: [380, 22], done: [70, 6.5], unsure: [24, 8], refused: [40, 10], error: [260, 18] };
  const B = (x, y, r, bx, by, br) => ({ x, y, r, bx: bx || 0, by: by || 0, br: br || 0 });
  const Z = B(0, 0, 0);
  // balls in units of the base radius; by/br = breath weights. Silhouette carries the state; L/C/h is a subtle secondary hue.
  const STATES = {
    // pebble/cloud: lumps of different sizes, off-axis; breath moves the lumps (bx/by) rather than stretching the body
    idle:      { balls: [B(-0.34, 0.06, 0.62, 0.06, -0.08, 0.02), B(0.30, -0.10, 0.70, -0.05, 0.07, 0.03), B(0.02, 0.34, 0.50, 0.08, 0.05, -0.02), B(-0.56, -0.30, 0.34, -0.06, -0.10, 0.03)], rate: .20, wobble: .035, swirl: 0, rot: 0,  drift: 1, rip: .08, L: .70, C: .010, h: 75,  glow: 0,   alpha: 1,   cue: 0, ring: 'none',       cueKind: null },
    listening: { balls: [B(-0.20, 0.02, 0.68, 0.03, -0.03, 0), B(0.42, -0.22, 0.60, -0.02, -0.04, 0), B(0.05, 0.36, 0.48, 0.02, 0.03, 0), Z],                                             rate: .50, wobble: .018, swirl: 0, rot: -6, drift: 0, rip: 1,   L: .72, C: .035, h: 55,  glow: .10, alpha: 1,   cue: 1, ring: 'level',      cueKind: 'opening' },
    thinking:  { balls: [B(-0.18, 0.04, 0.60, 0.02, 0, 0), B(0.22, -0.10, 0.58, -0.02, 0, .01), B(0.06, 0.28, 0.50, 0, 0.02, 0), B(-0.30, -0.28, 0.34, 0, -0.02, 0)],                        rate: .90, wobble: .006, swirl: 1, rot: 0,  drift: 0, rip: 0,   L: .66, C: .035, h: 240, glow: 0,   alpha: 1,   cue: 0, ring: 'confidence', cueKind: null },
    dictating: { balls: [B(-0.28, 0.06, 0.62, 0.02, -0.02, 0), B(0.26, -0.06, 0.66, -0.02, 0.02, 0), B(0.62, 0.22, 0.38, 0.03, 0.02, 0), B(-0.12, 0.36, 0.42, 0, 0.03, 0)],                    rate: .80, wobble: .010, swirl: 0, rot: 0,  drift: 0, rip: 0,   L: .70, C: .030, h: 90,  glow: 0,   alpha: 1,   cue: 0, ring: 'none',       cueKind: null },
    acting:    { balls: [B(-0.10, 0.06, 0.62), B(1.00, -0.12, 0.42), B(-0.60, 0.16, 0.40), B(0.30, 0.30, 0.34)],                                                                             rate: 1,   wobble: .006, swirl: 0, rot: 0,  drift: 0, rip: 0,   L: .70, C: .060, h: 45,  glow: .25, alpha: 1,   cue: 0, ring: 'confidence', cueKind: null },
    done:      { balls: [B(-0.34, 0.06, 0.62, 0.04, -0.05, 0.02), B(0.30, -0.10, 0.70, -0.03, 0.04, 0.03), B(0.02, 0.34, 0.50, 0.05, 0.03, -0.02), B(-0.56, -0.30, 0.34, -0.04, -0.06, 0.02)], rate: .22, wobble: .020, swirl: 0, rot: 0,  drift: 0, rip: 0,   L: .72, C: .040, h: 150, glow: 0,   alpha: 1,   cue: 0, ring: 'confidence', cueKind: null },
    unsure:    { balls: [B(-0.56, 0.42, 0.56, 0.04, 0.03, 0), B(0.50, 0.46, 0.60, -0.04, 0.03, 0), B(-0.04, 0.16, 0.60, 0, -0.03, -0.02), B(0.20, 0.52, 0.30, 0, 0.02, 0)],                     rate: .18, wobble: .060, swirl: 0, rot: -4, drift: 0, rip: 0,   L: .64, C: .005, h: 75,  glow: 0,   alpha: .80, cue: 0, ring: 'confidence', cueKind: null },
    refused:   { balls: [B(-0.36, 0.28, 0.58, 0.02, 0.02, 0), B(0.32, 0.30, 0.58, -0.02, 0.02, 0), B(-0.06, -0.06, 0.60, 0, -0.02, 0), Z],                                                    rate: .20, wobble: .012, swirl: 0, rot: 0,  drift: 0, rip: 0,   L: .60, C: .005, h: 75,  glow: 0,   alpha: .70, cue: 0, ring: 'none',       cueKind: null },
    error:     { balls: [B(-0.72, 0.50, 0.50, 0.02, 0.02, 0), B(0.68, 0.52, 0.50, -0.02, 0.02, 0), B(-0.04, 0.42, 0.58, 0, 0, 0), Z],                                                          rate: .30, wobble: .015, swirl: 0, rot: 0,  drift: 0, rip: 0,   L: .55, C: .040, h: 28,  glow: 0,   alpha: .70, cue: 0, ring: 'none',       cueKind: null }
  };
  const RETURN_MS = { done: 1500, unsure: 1800, refused: 2000, error: 1300 };
  const NUM = ['rot', 'drift', 'rip', 'wobble', 'swirl', 'L', 'a', 'b', 'glow', 'alpha', 'cue'];
  function resolve(s) { const o = Object.assign({}, s); const hr = s.h * Math.PI / 180; o.a = s.C * Math.cos(hr); o.b = s.C * Math.sin(hr); return o; }
  class Spring { constructor(v) { this.v = v; this.t = v; this.vel = 0; } step(dt, k, d) { const acc = k * (this.t - this.v) - d * this.vel; this.vel += acc * dt; this.v += this.vel * dt; } set(v) { this.v = this.t = v; this.vel = 0; } }
  const DEFAULT_COLORS = { accent: 'rgb(0,122,255)', track: 'rgba(0,0,0,0.12)', edge: 'rgba(0,0,0,0.22)', highlight: 'rgba(255,255,255,0.75)', scheme: 'light' };

  class YappAvatar {
    constructor(canvas, opts) {
      opts = opts || {};
      this.canvas = canvas; this.ctx = canvas.getContext('2d');
      this.size = opts.size || canvas.clientWidth || 64;
      this.g = {}; NUM.forEach(k => { this.g[k] = new Spring(0); });
      this.balls = []; for (let i = 0; i < NB; i++) this.balls.push({ x: new Spring(0), y: new Spring(0), r: new Spring(0), bx: 0, by: 0, br: 0 });
      this.level = new Spring(0); this.conf = new Spring(0); this.shiver = new Spring(0); this.tick = new Spring(0); this.ringV = new Spring(0);
      this.ringMode = 'none'; this.ringOverride = null;
      this.k = 30; this.d = 9; this.cueKind = null; this.timers = []; this.t = 0; this.last = performance.now(); this.rate = .2;
      this.autoLevel = !!opts.autoLevel; this.autoCommit = !!opts.autoCommit; this.hold = !!opts.hold; this.onchange = opts.onchange || null;
      this.returnTo = 'idle'; this.nextAuto = 0; this.contour = null;
      this.colors = Object.assign({}, DEFAULT_COLORS, opts.colors || {});
      this.resize(); this.syncColors();
      this.setState(opts.state || 'idle', { instant: true, level: opts.level, confidence: opts.confidence, direction: opts.direction });
      this._frame = this._frame.bind(this); this.raf = requestAnimationFrame(this._frame);
      if (global.matchMedia) { this._mq = global.matchMedia('(prefers-color-scheme: dark)'); this._mqFn = () => this.syncColors(); this._mq.addEventListener && this._mq.addEventListener('change', this._mqFn); }
    }
    resize(size) {
      if (size) this.size = size;
      const dpr = this.dpr = Math.min(3, global.devicePixelRatio || 1);
      this.canvas.width = Math.round(this.size * dpr); this.canvas.height = Math.round(this.size * dpr);
      if (this.canvas.style) { this.canvas.style.width = this.size + 'px'; this.canvas.style.height = this.size + 'px'; }
    }
    // resolve token colours (incl. the AccentColor system keyword) through the canvas's own computed style
    syncColors() {
      const c = this.canvas; if (!c.style || !global.getComputedStyle || !c.isConnected) return;
      const read = (v, fb) => { c.style.color = 'var(' + v + ', ' + fb + ')'; return global.getComputedStyle(c).color || fb; };
      this.colors.accent = read('--yapp-accent', DEFAULT_COLORS.accent);
      this.colors.track = read('--yapp-ring-track', DEFAULT_COLORS.track);
      this.colors.edge = read('--yapp-avatar-edge', DEFAULT_COLORS.edge);
      this.colors.highlight = read('--yapp-avatar-highlight', DEFAULT_COLORS.highlight);
      c.style.color = '';
      const sch = global.getComputedStyle(c).getPropertyValue('--yapp-scheme').trim();
      this.colors.scheme = sch || (this._mq && this._mq.matches ? 'dark' : 'light');
    }
    setLevel(v) { this.level.t = clamp01(v); }
    setConfidence(v) { this.conf.t = clamp01(v); }
    setRing(mode, v) { this.ringOverride = mode === null || mode === undefined ? null : mode; if (mode === 'countdown' && v != null) this.ringV.t = clamp01(v); if (mode === null) this.ringV.t = 0; }
    setCountdown(frac) { if (frac == null) { this.setRing(null); return; } if (this.ringOverride !== 'countdown') this.ringV.set(clamp01(frac)); this.setRing('countdown', frac); }
    _at(ms, fn) { this.timers.push(setTimeout(fn, ms)); }
    _targets(name, mod) {
      const bs = STATES[name].balls;
      for (let i = 0; i < NB; i++) {
        const b = bs[i] || Z, s = this.balls[i]; let x = b.x, y = b.y;
        if (mod && mod.dir) { const c = Math.cos(mod.dir), sn = Math.sin(mod.dir); const rx = x * c - y * sn, ry = x * sn + y * c; x = rx; y = ry; }
        if (mod && mod.lift) y -= mod.lift;
        s.x.t = x; s.y.t = y; s.r.t = b.r * (mod && mod.scale || 1); s.bx = b.bx; s.by = b.by; s.br = b.br;
        if (mod && mod.instant) { s.x.set(x); s.y.set(y); s.r.set(s.r.t); }
      }
    }
    setState(name, o) {
      o = o || {}; const s = STATES[name]; if (!s) return;
      if (o.commit && name === this.state && (name === 'listening' || name === 'dictating')) { this.commit(); this._apply(o); return; }
      this.timers.forEach(clearTimeout); this.timers = [];
      const prev = this.state; this.state = name;
      const r = resolve(s), sp = SPRINGS[name]; this.k = sp[0]; this.d = sp[1]; this.rate = s.rate; this.ringMode = s.ring;
      if (this.ringOverride === 'countdown' && name !== 'listening') this.ringOverride = null;
      NUM.forEach(key => { const G = this.g[key]; G.t = r[key]; if (o.instant) G.set(r[key]); });
      if (s.cue > 0) this.cueKind = s.cueKind;
      const dir = o.direction != null ? +o.direction : 0;
      this._targets(name, { dir, instant: o.instant });
      this._apply(o);
      if (name === 'idle' || name === 'listening') this.conf.t = o.confidence != null ? clamp01(o.confidence) : 0;
      if (name === 'acting') { this.returnTo = (prev === 'listening' || prev === 'dictating') ? prev : 'idle'; this._pulse(dir); }
      if (name === 'done') this._settle();
      if (name === 'unsure') this._shrug();
      if (name === 'error') this._shiverNow();
      if (RETURN_MS[name] && !this.hold) this._at(RETURN_MS[name], () => this.setState('idle'));
      if (this.onchange) this.onchange(name);
    }
    _apply(o) { if (o.level != null) this.setLevel(o.level); if (o.confidence != null) this.setConfidence(o.confidence); if (o.hold != null) this.hold = !!o.hold; }
    _pulse(dir) {
      this._targets('acting', { dir }); this.g.glow.t = .25;
      this.balls[1].r.vel += 3; this.balls[1].x.vel += 4 * Math.cos(dir); this.balls[1].y.vel += 4 * Math.sin(dir);
      this._at(170, () => { this._targets(this.returnTo); this.g.glow.t = 0; this.balls[0].r.vel += 1.2; });
      this._at(380, () => { if (!this.hold) return this.setState(this.returnTo); this._at(1400, () => this._pulse(dir)); });
    }
    _settle() {
      this.g.glow.set(.7); this.g.glow.t = 0;
      this.balls.forEach((b, i) => { if (i < 3) { b.x.vel += (i % 2 ? 1 : -1) * 1.6; b.y.vel += (i === 1 ? -1.8 : 1.2); b.r.vel += .6; } });
      if (this.hold) this._at(3000, () => this._settle());
    }
    _shrug() {
      this._targets('unsure', { lift: .18 }); this.g.rot.t = 5;
      this._at(240, () => { this._targets('unsure'); this.g.rot.t = -4; });
      if (this.hold) this._at(3200, () => this._shrug());
    }
    _shiverNow() {
      this.shiver.set(1); this.shiver.t = 0; this._targets('error', { scale: 1.06 });
      this._at(120, () => this._targets('error'));
      if (this.hold) this._at(2400, () => this._shiverNow());
    }
    commit() {
      if (this.state === 'listening') {
        const b = this.balls[3]; b.x.set(.70); b.y.set(-.50); b.r.set(0); b.r.t = .32; this.tick.set(1); this.tick.t = 0;
        this._at(110, () => { b.r.t = 0; b.x.t = .45; b.y.t = -.25; });
      } else if (this.state === 'dictating') {
        const m = this.balls[1], d = this.balls[2]; m.r.t += .06; d.x.t += .16; d.r.t += .06; this.g.glow.t = .15;
        this._at(120, () => { this._targets('dictating'); this.g.glow.t = 0; });
      } else { this.g.glow.t = .18; this._at(120, () => { this.g.glow.t = STATES[this.state].glow; }); }
    }
    destroy() { cancelAnimationFrame(this.raf); this.timers.forEach(clearTimeout); if (this._mq && this._mq.removeEventListener) this._mq.removeEventListener('change', this._mqFn); }
    _frame(now) {
      const dt = Math.min(.05, (now - this.last) / 1000); this.last = now; this.t += dt;
      NUM.forEach(k => this.g[k].step(dt, this.k, this.d));
      const kb = this.state === 'listening' ? 300 : this.k, db = this.state === 'listening' ? 18 : this.d;
      this.balls.forEach((b, i) => { const kk = i === 3 ? 320 : kb, dd = i === 3 ? 16 : db; b.x.step(dt, kk, dd); b.y.step(dt, kk, dd); b.r.step(dt, kk, dd); });
      if (this.autoLevel) this.level.t = this.state === 'listening' ? clamp01(.45 + .3 * Math.sin(this.t * 2.7) + .22 * Math.sin(this.t * 7.3) + .1 * Math.sin(this.t * 13.1)) : 0;
      if (this.autoCommit && (this.state === 'listening' || this.state === 'dictating') && this.t > this.nextAuto) { this.commit(); this.nextAuto = this.t + .55 + Math.random() * .6; }
      this.level.step(dt, 200, 22); this.conf.step(dt, 60, 14); this.shiver.step(dt, 30, 9); this.tick.step(dt, 120, 14); this.ringV.step(dt, 80, 16);
      this.draw(); this.raf = requestAnimationFrame(this._frame);
    }
    draw() {
      const ctx = this.ctx, S = this.size, dpr = this.dpr, t = this.t, g = this.g, C = this.colors, dark = C.scheme === 'dark';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, S, S);
      const R = S * .235, cx = S / 2, cy = S / 2 + S * .015;
      const L = g.L.v + (dark ? .05 : 0), a = g.a.v, b = g.b.v;
      const col = toRgb(L, a, b), hi = toRgb(Math.min(.97, L + .13), a * .6, b * .6), lo = toRgb(L - .08, a, b), deep = toRgb(L - .18, a * 1.2, b * 1.2);
      const lvl = this.level.v, rip = g.rip.v * lvl, dr = g.drift.v, wob = g.wobble.v, br = Math.sin(t * this.rate * TAU);
      const ox = cx + dr * R * .07 * Math.sin(t * .31) + this.shiver.v * Math.sin(t * 95) * R * .08;
      const oy = cy + dr * R * .05 * Math.sin(t * .23 + 1);
      const rot = (g.rot.v + dr * 2.5 * Math.sin(t * .17)) * Math.PI / 180, cr = Math.cos(rot), sr = Math.sin(rot);
      const bl = [];
      for (let i = 0; i < NB; i++) {
        const s = this.balls[i]; let x = s.x.v + s.bx * br, y = s.y.v + s.by * br, r = s.r.v + s.br * br;
        x += wob * .5 * Math.sin(t * .9 + i * 2.1); y += wob * .5 * Math.sin(t * .7 + i * 1.3);
        r += rip * .10 * Math.sin(t * 16 + i * 2.4) + wob * .3 * Math.sin(t * 1.1 + i);
        if (r <= .01) continue;
        bl.push([ox + (x * cr - y * sr) * R, oy + (x * sr + y * cr) * R, r * R]);
      }
      if (bl.length) {
        let wx = 0, wy = 0, ws = 0; bl.forEach(q => { const w = q[2] * q[2]; wx += q[0] * w; wy += q[1] * w; ws += w; }); wx /= ws; wy /= ws;
        const field = (x, y) => { let f = 0; for (let i = 0; i < bl.length; i++) { const dx = x - bl[i][0], dy = y - bl[i][1]; const q = bl[i][2] * bl[i][2] / (dx * dx + dy * dy + 1e-6); f += q * q; } return f; };
        let rmax = 0; bl.forEach(q => { rmax = Math.max(rmax, Math.hypot(q[0] - wx, q[1] - wy) + q[2]); }); rmax *= 1.15;
        const N = 40, pts = [], ripHF = rip * R * .06;
        for (let i = 0; i < N; i++) {
          const th = i / N * TAU, c = Math.cos(th), s = Math.sin(th);
          let hiR = rmax, loR = 0, step = rmax / 22, d = rmax;
          for (; d > 0; d -= step) { if (field(wx + c * d, wy + s * d) >= 1) { loR = d; hiR = d + step; break; } }
          for (let j = 0; j < 6; j++) { const m = (loR + hiR) / 2; if (field(wx + c * m, wy + s * m) >= 1) loR = m; else hiR = m; }
          const rr = (loR + hiR) / 2 + ripHF * Math.sin(7 * th + t * 15) * .5;
          pts.push([wx + c * rr, wy + s * rr]);
        }
        this.contour = pts;
        const path = new Path2D(); path.moveTo(pts[0][0], pts[0][1]);
        for (let i = 0; i < N; i++) {
          const p0 = pts[(i - 1 + N) % N], p1 = pts[i], p2 = pts[(i + 1) % N], p3 = pts[(i + 2) % N];
          path.bezierCurveTo(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6, p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, p2[0], p2[1]);
        }
        path.closePath();
        ctx.globalAlpha = clamp01(g.alpha.v);
        const glow = g.glow.v;
        if (glow > .01) { ctx.save(); ctx.shadowBlur = glow * 22; ctx.shadowColor = rgba(col, Math.min(1, glow)); ctx.fillStyle = rgba(col, 1); ctx.fill(path); ctx.restore(); }
        if (dark) { ctx.save(); ctx.shadowBlur = 6; ctx.shadowOffsetY = 2; ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.fillStyle = rgba(col, 1); ctx.fill(path); ctx.restore(); }
        const m = bl[0], gr = ctx.createRadialGradient(m[0] - m[2] * .45, m[1] - m[2] * .5, m[2] * .1, wx, wy, rmax * .95);
        gr.addColorStop(0, rgba(hi, 1)); gr.addColorStop(.5, rgba(col, 1)); gr.addColorStop(1, rgba(lo, 1));
        ctx.fillStyle = gr; ctx.fill(path);
        const swirl = g.swirl.v;
        if (swirl > .01) {
          ctx.save(); ctx.clip(path);
          const an = t * 1.7, x1 = wx + Math.cos(an) * R * .3, y1 = wy + Math.sin(an * 1.3) * R * .5;
          const g2 = ctx.createRadialGradient(x1, y1, 0, x1, y1, R * .8); g2.addColorStop(0, rgba(deep, swirl * .6)); g2.addColorStop(1, rgba(deep, 0));
          ctx.fillStyle = g2; ctx.fillRect(0, 0, S, S);
          const x2 = wx - Math.cos(an * .8 + 1) * R * .28, y2 = wy - Math.sin(an * 1.1 + 1) * R * .45;
          const g3 = ctx.createRadialGradient(x2, y2, 0, x2, y2, R * .6); g3.addColorStop(0, rgba(hi, swirl * .5)); g3.addColorStop(1, rgba(hi, 0));
          ctx.fillStyle = g3; ctx.fillRect(0, 0, S, S); ctx.restore();
        }
        ctx.lineWidth = 1; ctx.strokeStyle = C.edge; ctx.stroke(path);
        const cue = g.cue.v;
        if (cue > .01 && this.cueKind === 'opening' && bl[1]) {
          ctx.save(); ctx.clip(path);
          const ax = bl[1][0], ay = bl[1][1], rr = bl[1][2] * (.7 + .5 * lvl + .4 * this.tick.v);
          const g4 = ctx.createRadialGradient(ax, ay, 0, ax, ay, rr); g4.addColorStop(0, 'rgba(255,255,255,' + cue * (.5 + .35 * lvl + .3 * this.tick.v) + ')'); g4.addColorStop(1, 'rgba(255,255,255,0)');
          ctx.fillStyle = g4; ctx.fillRect(0, 0, S, S); ctx.restore();
        }
        ctx.globalAlpha = 1;
      }
      // ring: mic level while listening, confidence while deciding/acting, a draining countdown in silence
      const mode = this.ringOverride || this.ringMode;
      if (mode !== 'none') {
        const frac = mode === 'level' ? Math.min(1, .06 + lvl * .94) : mode === 'countdown' ? this.ringV.v : this.conf.v;
        const rr = S / 2 - 2; ctx.lineWidth = 2; ctx.lineCap = 'round';
        ctx.strokeStyle = C.track; ctx.beginPath(); ctx.arc(cx, S / 2, rr, 0, TAU); ctx.stroke();
        if (frac > .004) { ctx.strokeStyle = C.accent; ctx.beginPath(); ctx.arc(cx, S / 2, rr, -Math.PI / 2, -Math.PI / 2 + TAU * Math.min(1, frac)); ctx.stroke(); }
      }
    }
  }
  YappAvatar.STATES = Object.keys(STATES); YappAvatar.SPRINGS = SPRINGS; YappAvatar.toRgb = toRgb;
  global.YappAvatar = YappAvatar;
})(typeof window !== 'undefined' ? window : this);
