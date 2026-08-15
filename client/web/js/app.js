/* ============================================================
   Africana Tracker — App Controller
   Wires the QWebChannel bridge to the UI and renders all views.
   ============================================================ */
'use strict';

window.__errors = [];
window.addEventListener('error', (e) => window.__errors.push(String(e.message || e.error)));

const PHASES = ['PRE-FLIGHT', 'TAXI OUT', 'TAKEOFF', 'CLIMB', 'CRUISE',
                'DESCENT', 'APPROACH', 'LANDING', 'TAXI IN', 'PARKED'];
const PHASE_SHORT = ['PRE', 'TAXI', 'T/O', 'CLB', 'CRZ', 'DES', 'APP', 'LDG', 'TXI', 'PRK'];

const App = {
  bridge: null,
  state: {
    ofp: null, tracking: false, weightUnit: 'LBS', pinned: false,
    totalRouteNm: null, pilots: {}, loginKeyMode: false,
  },

  // ── init ──────────────────────────────────────────────
  init() {
    AfvMap.init();
    this._buildPhaseTrack();
    this._wireChrome();
    this._wireNav();
    this._wireActions();
    this._wireLogin();

    new QWebChannel(qt.webChannelTransport, (channel) => {
      this.bridge = channel.objects.bridge;
      this.bridge.event.connect((type, payload) => this._onEvent(type, payload));
      this.send('ready');
    });
  },

  send(action, payload) {
    if (this.bridge) this.bridge.send(action, JSON.stringify(payload || {}));
  },

  // ── Window chrome ─────────────────────────────────────
  _wireChrome() {
    const tb = document.getElementById('titlebar');
    tb.addEventListener('mousedown', (e) => {
      if (e.target.closest('.no-drag')) return;
      if (e.button === 0) this.send('window:move');
    });
    tb.addEventListener('dblclick', (e) => {
      if (!e.target.closest('.no-drag')) this.send('window:max');
    });
    document.getElementById('btn-min').onclick = () => this.send('window:min');
    document.getElementById('btn-max').onclick = () => this.send('window:max');
    document.getElementById('btn-close').onclick = () => this.send('window:close');
    document.getElementById('btn-pin').onclick = (e) => {
      this.state.pinned = !this.state.pinned;
      e.currentTarget.classList.toggle('active', this.state.pinned);
      this.send('window:pin', { on: this.state.pinned });
    };
  },

  _wireNav() {
    document.querySelectorAll('.nav-item').forEach((btn) => {
      btn.onclick = () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        btn.classList.add('active');
        const view = btn.dataset.view;
        document.getElementById('view-' + view).classList.add('active');
        if (view === 'logbook') { this.send('history:refresh'); this.send('profile:refresh'); }
        if (view === 'flights') this.send('bids:refresh');
      };
    });
  },

  _wireActions() {
    document.getElementById('track-btn').onclick = () => this.send('track:toggle');
    document.getElementById('map-recenter').onclick = () => AfvMap.recenter();
    document.getElementById('btn-fetch-simbrief').onclick = (e) => {
      e.currentTarget.classList.add('loading');
      this.send('simbrief:fetch');
    };
    document.getElementById('btn-save-settings').onclick = () => this._saveSettings();
    document.getElementById('btn-test-conn').onclick = () => {
      this.toast('info', 'Testing phpVMS connection…');
      this.send('connection:test');
    };
    document.getElementById('gb-close').onclick = () =>
      document.getElementById('gate-banner').hidden = true;
    document.getElementById('fc-later').onclick = () =>
      document.getElementById('fc-modal').hidden = true;
    document.getElementById('fc-submit').onclick = (e) => {
      const btn = e.currentTarget;
      if (btn.dataset.done === '1') { document.getElementById('fc-modal').hidden = true; return; }
      btn.classList.add('loading');
      btn.disabled = true;
      this.send('pirep:submit');
    };
  },

  // ── Login gate ────────────────────────────────────────
  _wireLogin() {
    const btn = document.getElementById('login-btn');
    const submit = () => {
      const err = document.getElementById('login-error');
      err.hidden = true;
      let payload;
      if (this.state.loginKeyMode) {
        const key = document.getElementById('login-key').value.trim();
        if (!key) return this._loginError('Paste your phpVMS API key.');
        payload = { api_key: key };
      } else {
        const email = document.getElementById('login-email').value.trim();
        const password = document.getElementById('login-password').value;
        if (!email || !password) return this._loginError('Enter your email and password.');
        payload = { email, password };
      }
      btn.classList.add('loading');
      btn.disabled = true;
      this.send('login:submit', payload);
    };
    btn.onclick = submit;
    ['login-email', 'login-password', 'login-key'].forEach(id =>
      document.getElementById(id).addEventListener('keydown', e => {
        if (e.key === 'Enter') submit();
      }));
    document.getElementById('login-alt').onclick = (e) => {
      this.state.loginKeyMode = !this.state.loginKeyMode;
      document.getElementById('login-cred-fields').hidden = this.state.loginKeyMode;
      document.getElementById('login-key-fields').hidden = !this.state.loginKeyMode;
      document.getElementById('login-error').hidden = true;
      e.currentTarget.textContent = this.state.loginKeyMode
        ? 'Use email & password instead' : 'Use API key instead';
    };
    document.getElementById('btn-logout').onclick = () => this.send('logout');
  },

  _loginError(msg) {
    const err = document.getElementById('login-error');
    err.textContent = msg;
    err.hidden = false;
    const btn = document.getElementById('login-btn');
    btn.classList.remove('loading');
    btn.disabled = false;
  },

  _setLoginVisible(show) {
    document.getElementById('login-scrim').hidden = !show;
    if (show) {
      const btn = document.getElementById('login-btn');
      btn.classList.remove('loading');
      btn.disabled = false;
      document.getElementById('login-password').value = '';
    }
  },

  // ── Phase timeline ────────────────────────────────────
  _buildPhaseTrack() {
    const track = document.getElementById('phase-track');
    track.innerHTML = PHASES.map((_, i) =>
      `<div class="phase-node" data-i="${i}"><span class="phase-dot"></span><span class="phase-lbl">${PHASE_SHORT[i]}</span></div>`
    ).join('');
  },
  _setPhase(phase) {
    const idx = PHASES.indexOf(phase);
    document.querySelectorAll('.phase-node').forEach((n, i) => {
      n.classList.toggle('done', i < idx);
      n.classList.toggle('active', i === idx);
    });
    const el = document.getElementById('fh-phase');
    if (el) el.textContent = phase;
  },

  // ── Event router (Python → JS) ────────────────────────
  _onEvent(type, payloadJson) {
    let d = {};
    try { d = JSON.parse(payloadJson); } catch (_) {}
    const h = this._handlers[type];
    if (h) h.call(this, d);
    else console.debug('unhandled event', type, d);
  },

  _handlers: {
    clock(d) { const c = document.getElementById('clock'); c.innerHTML = `${d.utc}<span class="z">UTC</span>`; },

    settings(cfg) {
      App._fillSettings(cfg);
      App._setLoginVisible(!(cfg.Pilot_Key || '').trim());
    },

    'login:result'(d) {
      if (d.success) {
        App._setLoginVisible(false);
        App.toast('success', d.name ? `Welcome, ${d.name}!` : 'Signed in.');
      } else {
        App._loginError(d.error || 'Sign-in failed.');
      }
    },

    sim(d) { App._pill('pill-sim', d.connected, d.retrying ? 'warn' : ''); },
    phpvms(d) { App._pill('pill-phpvms', d.connected, d.label && d.label.includes('no key') ? 'warn' : ''); },
    simbrief(d) {
      App._pill('pill-simbrief', d.connected);
      if (!d.loading) document.getElementById('btn-fetch-simbrief').classList.remove('loading');
    },
    network(d) { App._pill('pill-network', d.connected); },

    tracking(d) {
      App.state.tracking = d.active;
      const btn = document.getElementById('track-btn');
      btn.classList.toggle('tracking', d.active);
      document.getElementById('track-label').textContent = d.active ? 'STOP TRACKING' : 'START TRACKING';
      btn.querySelector('.tb-ico').textContent = d.active ? '■' : '▶';
      if (d.active) AfvMap.clearTrail();
    },

    ofp(o) { App._renderOfp(o); },
    'ofp:error'(d) { App.toast('error', d.message || 'SimBrief error'); },

    phase(d) { App._setPhase(d.phase); },

    telemetry(t) { App._renderTelemetry(t); },

    bid(b) { App._renderMatchedBid(b); },
    bids(list) { App._renderBids(list); },
    prefile(d) { App.toast('success', `PIREP #${d.pirep_id} ready.`); },

    history(list) { App._renderHistory(list); },
    profile(p) { App._renderProfile(p); },

    roster(list) {
      App.state.pilots = {};
      list.forEach(p => App.state.pilots[p.pilot_id] = p);
      App._renderRoster();
    },
    pilot(p) { App.state.pilots[p.pilot_id] = p; App._renderRoster(); },
    'pilot:offline'(d) { delete App.state.pilots[d.pilot_id]; App._renderRoster(); },

    gate(d) { App._renderGate(d); },
    'gate:board'() {},
    'gate:remote_assigned'() {},
    'gate:remote_released'() {},

    flightComplete(d) { App._renderFlightComplete(d); },
    pirepResult(d) { App._renderPirepResult(d); },

    toast(d) { App.toast(d.level || 'info', d.message); },
  },

  _pill(id, on, cls) {
    const el = document.getElementById(id);
    el.classList.toggle('on', !!on);
    el.classList.toggle('warn', cls === 'warn');
  },

  // ── Renderers ─────────────────────────────────────────
  _renderOfp(o) {
    this.state.ofp = o;
    this.state.totalRouteNm = o.distance_nm || null;
    document.getElementById('fh-callsign').textContent = o.callsign || o.flight_number || 'FLIGHT';
    document.getElementById('fh-aircraft').textContent =
      `${o.aircraft_icao || ''} ${o.aircraft_name || ''} · ${o.registration || ''}`.trim();
    document.getElementById('fh-origin').textContent = o.origin_icao || '----';
    document.getElementById('fh-dest').textContent = o.destination_icao || '----';
    document.getElementById('fh-origin-name').textContent = o.origin_name || 'Departure';
    document.getElementById('fh-dest-name').textContent = o.destination_name || 'Arrival';
    document.getElementById('rc-origin').textContent = o.origin_icao || '----';
    document.getElementById('rc-dest').textContent = o.destination_icao || '----';

    if (o.origin_coords && o.dest_coords)
      AfvMap.setRoute(o.origin_coords, o.dest_coords, o.origin_icao, o.destination_icao);

    // OFP summary card on Flights view
    const wrap = document.getElementById('ofp-summary');
    wrap.hidden = false;
    const w = this._wunit(o.fuel_lbs);
    wrap.innerHTML = [
      ['FLIGHT', o.callsign || o.flight_number],
      ['ROUTE', `${o.origin_icao} → ${o.destination_icao}`],
      ['AIRCRAFT', o.aircraft_icao || '—'],
      ['CRZ ALT', o.cruise_altitude ? 'FL' + Math.round(o.cruise_altitude / 100) : '—'],
      ['DISTANCE', (o.distance_nm || 0) + ' nm'],
      ['EST TIME', this._mins(o.est_flight_time_min)],
      ['BLOCK FUEL', w],
      ['ETD → ETA', `${o.atd_utc || '--'} → ${o.eta_utc || '--'}`],
    ].map(([k, v]) => `<div class="ofp-cell"><span class="k">${k}</span><span class="v">${v}</span></div>`).join('');
  },

  _renderTelemetry(t) {
    const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    set('t-alt', (t.altitude_ft || 0).toLocaleString());
    set('t-ias', t.ias_kts);
    set('t-gs', t.gs_kts);
    const vs = document.getElementById('t-vs');
    vs.textContent = (t.vs_fpm > 0 ? '+' : '') + t.vs_fpm;
    vs.style.color = t.vs_fpm > 100 ? 'var(--green)' : t.vs_fpm < -100 ? 'var(--amber)' : 'var(--text)';
    set('t-hdg', String(t.heading).padStart(3, '0'));
    set('t-mach', (t.mach || 0).toFixed(3));
    set('t-fuel', this._wconv(t.fuel_lbs));
    set('t-fuel-u', this.state.weightUnit.toLowerCase());
    set('t-wind', `${String(t.wind_dir).padStart(3, '0')}/${t.wind_kts}`);

    // progress
    set('p-elapsed', this._clock(t.elapsed_sec));
    set('p-flown', `${t.dist_flown_nm} <i>nm</i>`);
    document.getElementById('p-flown').innerHTML = `${t.dist_flown_nm} <i>nm</i>`;
    document.getElementById('p-togo').innerHTML =
      (t.dist_to_dest_nm != null ? t.dist_to_dest_nm : '---') + ' <i>nm</i>';
    if (this.state.totalRouteNm && t.dist_to_dest_nm != null) {
      const pct = Math.max(0, Math.min(100, (1 - t.dist_to_dest_nm / this.state.totalRouteNm) * 100));
      document.getElementById('prog-fill').style.width = pct + '%';
    }
    AfvMap.updateAircraft(t.lat, t.lon, t.heading);
  },

  _renderBids(list) {
    const grid = document.getElementById('bids-grid');
    if (!list || !list.length) { grid.innerHTML = '<div class="empty">No bids. Book a flight on the website, then refresh.</div>'; return; }
    const matchNum = this.state.ofp && this.state.ofp.flight_number;
    grid.innerHTML = list.map(b => `
      <div class="bid ${String(b.flight_number) == String(matchNum) ? 'matched' : ''}" data-id="${b.id}">
        <div class="bid-top"><span class="bid-num">${b.flight_number || '—'}</span>
          ${String(b.flight_number) == String(matchNum) ? '<span class="bid-badge">OFP MATCH</span>' : ''}</div>
        <div class="bid-route"><span>${b.dpt_airport || '???'}</span><span class="a">→</span><span>${b.arr_airport || '???'}</span></div>
        <div class="bid-meta"><span>${b.aircraft || 'Aircraft'}</span><span><b>${this._nm(b.distance)}</b> nm</span></div>
      </div>`).join('');
    grid.querySelectorAll('.bid').forEach(el =>
      el.onclick = () => { this.send('bid:select', { bid_id: el.dataset.id }); this.toast('info', 'Loading bid…'); });
  },
  _renderMatchedBid(b) { /* highlight handled via bids list + toast in prefile */ },

  _renderHistory(list) {
    const wrap = document.getElementById('logbook-list');
    if (!list || !list.length) { wrap.innerHTML = '<div class="empty">No PIREPs filed yet.</div>'; return; }
    wrap.innerHTML = list.map(p => {
      const st = (p.state === 2) ? 'ok' : (p.state === 6 ? 'rejected' : 'pending');
      const stLabel = (p.state === 2) ? 'ACCEPTED' : (p.state === 6 ? 'REJECTED' : 'PENDING');
      return `<div class="log-row">
        <span class="log-num">${p.flight_number || '—'}</span>
        <span class="log-route">${p.dpt_airport || '???'} <span class="a">→</span> ${p.arr_airport || '???'}</span>
        <span class="log-metric"><b>${this._mins(p.flight_time)}</b>${this._nm(p.distance)} nm</span>
        <span class="status-badge ${st}">${stLabel}</span>
      </div>`;
    }).join('');
  },

  _renderProfile(p) {
    const cards = document.getElementById('profile-cards');
    cards.innerHTML = [
      ['sv', p.name || '—', 'Pilot'],
      ['sv gold', p.rank || '—', 'Rank'],
      ['sv', p.flights ?? 0, 'Flights'],
      ['sv', p.flight_time_str || '0h', 'Total Hours'],
    ].map(([cls, v, l]) => `<div class="stat-card"><div class="${cls}">${v}</div><div class="sl">${l}</div></div>`).join('');
  },

  _renderRoster() {
    const wrap = document.getElementById('roster-list');
    const pilots = Object.values(this.state.pilots);
    if (!pilots.length) { wrap.innerHTML = '<div class="empty">No other pilots online right now.</div>'; return; }
    wrap.innerHTML = pilots.map(p => {
      const nm = p.name || p.pilot_id || '??';
      return `<div class="roster-row">
        <div class="roster-av">${nm.substring(0, 2).toUpperCase()}</div>
        <div class="roster-info">
          <div class="roster-name">${nm}</div>
          <div class="roster-route">${p.origin || '???'} → ${p.destination || '???'} · ${(p.alt || 0).toLocaleString()} ft</div>
        </div>
        <div class="roster-phase">${p.phase || '—'}</div>
      </div>`;
    }).join('');
  },

  _renderGate(d) {
    const banner = document.getElementById('gate-banner');
    if (!d || !d.gate_number) { banner.hidden = true; return; }
    document.getElementById('gb-gate').textContent =
      d.gate_number + (d.airport ? ' · ' + d.airport : '');
    banner.hidden = false;
  },

  _renderFlightComplete(d) {
    document.getElementById('fc-badge').textContent = '✓';
    document.getElementById('fc-title').textContent = 'Flight Complete';
    document.getElementById('fc-flight').textContent =
      `${d.flight_number || ''}  ·  ${d.origin || ''} → ${d.destination || ''}`;
    document.getElementById('fc-stats').innerHTML = [
      ['BLOCK TIME', d.flight_time || '—'],
      ['LANDING', d.landing_rate != null ? Math.round(d.landing_rate) + ' fpm' : 'N/A'],
      ['DISTANCE', d.distance_flown_nm != null ? Math.round(d.distance_flown_nm) + ' nm' : '—'],
      ['FUEL USED', d.fuel_used_lbs != null ? this._wconv(d.fuel_used_lbs) + ' ' + this.state.weightUnit.toLowerCase() : '—'],
    ].map(([k, v]) => `<div class="fc-stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');

    const msg = document.getElementById('fc-msg');
    const submit = document.getElementById('fc-submit');
    submit.classList.remove('loading');
    submit.disabled = false;
    submit.dataset.done = '';
    submit.innerHTML = '<span class="spin-slot"></span> Submit PIREP';
    document.getElementById('fc-later').hidden = false;
    if (d.has_pirep === false) {
      msg.className = 'fc-msg';
      msg.textContent = 'No active PIREP on phpVMS — the prefile didn’t succeed (check that your bid’s aircraft is available). Submitting won’t work until that’s fixed.';
      msg.hidden = false;
    } else {
      msg.hidden = true;
    }
    document.getElementById('fc-modal').hidden = false;
  },

  _renderPirepResult(d) {
    const msg = document.getElementById('fc-msg');
    const submit = document.getElementById('fc-submit');
    submit.classList.remove('loading');
    if (d.success) {
      document.getElementById('fc-badge').textContent = '✓';
      msg.className = 'fc-msg ok';
      msg.textContent = d.message || 'PIREP filed on phpVMS.';
      msg.hidden = false;
      submit.disabled = false;
      submit.dataset.done = '1';
      submit.textContent = 'Close';
      document.getElementById('fc-later').hidden = true;
    } else {
      msg.className = 'fc-msg';
      msg.textContent = d.message || 'PIREP filing failed.';
      msg.hidden = false;
      submit.disabled = false;
      submit.dataset.done = '';
      submit.innerHTML = '<span class="spin-slot"></span> Retry Submit';
    }
  },

  // ── Settings ──────────────────────────────────────────
  _fillSettings(cfg) {
    this.state.weightUnit = cfg.weight_unit || 'LBS';
    const v = (id, val) => { const e = document.getElementById(id); if (e) e.value = val ?? ''; };
    const c = (id, val) => { const e = document.getElementById(id); if (e) e.checked = !!val; };
    v('s-vatsim', cfg.vatsim_cid); v('s-simbrief', cfg.simbrief_id);
    v('s-name', cfg.pilot_name); v('s-discord', cfg.discord);
    v('s-vaurl', cfg.VA_URL); v('s-pilotkey', cfg.Pilot_Key);
    v('s-weight', cfg.weight_unit || 'LBS'); v('s-poll', cfg.simconnect_poll_interval || 5);
    c('s-sound', cfg.sound_enabled); c('s-discord-rpc', cfg.discord_rpc_enabled);
  },
  _saveSettings() {
    const g = id => document.getElementById(id).value;
    const gc = id => document.getElementById(id).checked;
    this.send('settings:save', {
      vatsim_cid: g('s-vatsim').trim(), simbrief_id: g('s-simbrief').trim(),
      pilot_name: g('s-name').trim(), discord: g('s-discord').trim(),
      VA_URL: g('s-vaurl').trim(), Pilot_Key: g('s-pilotkey').trim(),
      weight_unit: g('s-weight'), simconnect_poll_interval: parseInt(g('s-poll')) || 5,
      sound_enabled: gc('s-sound'), discord_rpc_enabled: gc('s-discord-rpc'),
    });
  },

  // ── Helpers ───────────────────────────────────────────
  _wconv(lbs) { return this.state.weightUnit === 'KG' ? Math.round(lbs * 0.453592).toLocaleString() : Math.round(lbs || 0).toLocaleString(); },
  _wunit(lbs) { return this._wconv(lbs) + ' ' + this.state.weightUnit.toLowerCase(); },
  _nm(v) { const n = parseFloat(v); return isNaN(n) ? '—' : Math.round(n).toLocaleString(); },
  _mins(m) { m = parseInt(m) || 0; return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`; },
  _clock(s) { s = parseInt(s) || 0; const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
    return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`; },

  toast(level, msg) {
    if (!msg) return;
    const stack = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast ' + level;
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(() => { el.classList.add('hide'); setTimeout(() => el.remove(), 300); }, 4200);
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
