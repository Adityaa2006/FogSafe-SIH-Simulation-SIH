/* FogSafe Control Room dashboard logic */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

async function post(url, body = {}) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

const NODES = {
  ENTRY: [50, 420], N1: [200, 330], N2: [350, 220], N3: [350, 400],
  N4: [520, 150], N5: [520, 330], N6: [700, 220], PLANT: [850, 120],
};
const ROAD_EDGES = [
  ['ENTRY', 'N1'], ['N1', 'N2'], ['N1', 'N3'], ['N2', 'N4'], ['N2', 'N5'],
  ['N3', 'N5'], ['N4', 'N6'], ['N5', 'N6'], ['N6', 'PLANT'], ['N5', 'PLANT'],
];

let currentState = null;
let selectedVehicle = null;
let prevConnected = {};
let shownDriverRequestIds = new Set();
let shownConnLostFor = new Set();

/* ---------- toolbar actions ---------- */
async function setFog(level) { try { await post('/api/fog', { fog: level }); refresh(); } catch (e) { alert(e.message); } }
async function toggleFogAuto() {
  try {
    const nowAuto = currentState ? !!currentState.fog_auto : true;
    await post('/api/fog/auto', { auto: !nowAuto });
    refresh();
  } catch (e) { alert(e.message); }
}
async function toggleSimulation() {
  try { await post('/api/simulation', { running: !(currentState && currentState.running) }); refresh(); } catch (e) { alert(e.message); }
}
async function resetAll() { try { await post('/api/reset', {}); selectedVehicle = null; shownDriverRequestIds = new Set(); shownConnLostFor = new Set(); refresh(); } catch (e) { alert(e.message); } }
async function addHazard(a, b) { try { await post('/api/hazard', { a, b }); refresh(); } catch (e) { alert(e.message); } }
async function clearHazards() { try { await post('/api/clear-hazards', {}); refresh(); } catch (e) { alert(e.message); } }

/* ---------- vehicle control ---------- */
async function setVehicleSpeed(vid, speed) { try { await post(`/api/speed/${vid}`, { speed }); refresh(); } catch (e) { alert(e.message); } }
async function connectVehicle(vid) { try { await post(`/api/connect/${vid}`, {}); refresh(); } catch (e) { alert(e.message); } }
async function disconnectVehicle(vid) { try { await post(`/api/disconnect/${vid}`, {}); refresh(); } catch (e) { alert(e.message); } }
function selectVehicle(vid) { selectedVehicle = vid; renderSelected(); renderRoute(); }

/* ---------- emergency ---------- */
async function acknowledgeDriverEmergency(vid) { try { await post('/api/emergency/clear/' + vid, {}); closeDriverEmergencyPopup(); refresh(); } catch (e) { alert(e.message); } }
async function allOkDashboard() { try { await post('/api/emergency/all-ok', {}); refresh(); } catch (e) { alert(e.message); } }

/* ---------- incidents (quick panel) ---------- */
async function quickIncident() {
  try {
    await post('/api/emergency/incident', {
      type: $('quickIncidentType').value,
      road: $('quickIncidentRoad').value,
      reason: $('quickIncidentReason').value,
    });
    $('quickIncidentReason').value = '';
    refresh();
  } catch (e) { alert(e.message); }
}
async function clearQuickIncident(id) { try { await post('/api/emergency/incident/clear/' + id, {}); refresh(); } catch (e) { alert(e.message); } }

/* ---------- V2V ---------- */
async function connectV2V() {
  try {
    const a = $('msgFrom').value, b = $('msgTo').value;
    if (!a || !b || a === b) { alert('Pick two different vehicles to link.'); return; }
    await post('/api/v2v/connect', { a, b });
    refresh();
  } catch (e) { alert(e.message); }
}
async function disconnectV2V(a, b) { try { await post('/api/v2v/disconnect', { a, b }); refresh(); } catch (e) { alert(e.message); } }
async function sendMessage() {
  try {
    const from = $('msgFrom').value, to = $('msgTo').value, text = $('msgText').value.trim();
    if (!text) return;
    if (from === 'CTRL') { await post('/api/control/message', { to, message: text, level: $('msgLevel').value }); }
    else { await post('/api/v2v/message', { from, to, message: text }); }
    $('msgText').value = '';
    refresh();
  } catch (e) { alert(e.message); }
}

/* ---------- popups ---------- */
function closeConnectionLostPopup() { $('connectionLostPopup').classList.remove('show'); $('connectionLostPopup').setAttribute('aria-hidden', 'true'); }
function closeDriverEmergencyPopup() { $('driverEmergencyPopup').classList.remove('show'); $('driverEmergencyPopup').setAttribute('aria-hidden', 'true'); }

/* ---------- rendering ---------- */
function renderMap(d) {
  const svg = $('mineMap');
  let html = '';
  for (const [a, b] of ROAD_EDGES) {
    const key = [a, b].sort().join('-');
    const [x1, y1] = NODES[a], [x2, y2] = NODES[b];
    const isHazard = (d.hazards || []).includes(key);
    const conflict = (d.road_conflicts || []).some(c => c.road === key);
    html += `<line class="road${isHazard ? ' hazard' : ''}${conflict ? ' conflict-road' : ''}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`;
  }
  // route of the selected vehicle
  if (selectedVehicle && d.vehicles[selectedVehicle] && d.vehicles[selectedVehicle].route && d.vehicles[selectedVehicle].route.length > 1) {
    const pts = d.vehicles[selectedVehicle].route.map(n => NODES[n].join(',')).join(' ');
    html += `<polyline class="route" points="${pts}"></polyline>`;
  }
  for (const [id, [x, y]] of Object.entries(NODES)) {
    html += `<circle class="node" cx="${x}" cy="${y}" r="12"></circle><text class="node-label" x="${x}" y="${y - 18}">${id}</text>`;
  }
  for (const [a, b] of (d.v2v || [])) {
    const va = d.vehicles[a], vb = d.vehicles[b];
    if (!va || !vb) continue;
    html += `<line class="v2v-line" x1="${va.map_x}" y1="${va.map_y}" x2="${vb.map_x}" y2="${vb.map_y}"></line>`;
  }
  for (const [vid, v] of Object.entries(d.vehicles)) {
    const cls = !v.connected ? 'disconnected' : (v.risk_status || 'safe').toLowerCase();
    html += `<g class="vehicle ${cls}" onclick="selectVehicle('${vid}')">
      <circle class="vehicle-dot" cx="${v.map_x}" cy="${v.map_y}" r="14"></circle>
      <text class="vehicle-icon" x="${v.map_x}" y="${v.map_y + 5}">${v.status === 'EMERGENCY' ? '🚨' : '🚚'}</text>
      <text class="vehicle-label" x="${v.map_x}" y="${v.map_y - 20}">${vid}${selectedVehicle === vid ? ' ●' : ''}</text>
    </g>`;
  }
  svg.innerHTML = html;
}

function renderKpis(d) {
  const vs = Object.values(d.vehicles);
  $('kActive').textContent = vs.filter(v => v.connected).length;
  $('kSafe').textContent = `${vs.filter(v => v.risk_status === 'SAFE').length} / ${vs.filter(v => v.risk_status === 'CAUTION').length}`;
  $('kRisk').textContent = `${vs.filter(v => v.risk_status === 'HIGH').length} / ${vs.filter(v => v.risk_status === 'CRITICAL').length}`;
  $('kV2V').textContent = (d.v2v || []).length;
  $('kHazards').textContent = (d.hazards || []).length;
}

function renderAiSafety(d) {
  const box = $('aiSafetyStatus'), info = $('aiSafetyInfo');
  const conflicts = (d.road_conflicts || []).length;
  if (d.fog === 'critical') {
    box.className = 'ai-safety-active'; box.textContent = 'CRITICAL FOG — SPEED LIMITED';
    info.textContent = 'AI has capped vehicle speed fleet-wide due to critical fog conditions.';
  } else if (conflicts > 0) {
    box.className = 'ai-safety-warning'; box.textContent = `MANAGING ${conflicts} ENCOUNTER${conflicts > 1 ? 'S' : ''}`;
    info.textContent = 'AI is yielding a vehicle for opposite-direction traffic until safe separation is restored.';
  } else {
    box.className = 'ai-safety-ready'; box.textContent = 'MONITORING';
    info.textContent = 'AI monitors collision risk, opposite-direction traffic and critical fog conditions. Automatic emergency activates only at critical thresholds.';
  }
}

function renderEnvironment(d) {
  $('fogBadge').textContent = d.fog.toUpperCase();
  $('fogBadge').className = 'fog ' + d.fog;
  $('safeSpeed').textContent = d.safe_speed + ' km/h';
  $('followDistance').textContent = d.follow_distance + ' m';
  $('simStatus').textContent = d.running ? 'RUNNING' : 'PAUSED';
  $('fogSensorScore').textContent = `${d.fog_sensor.toFixed(1)} / 100`;
  $('fogModeLabel').textContent = d.fog_auto ? 'AUTO' : 'MANUAL OVERRIDE';
  $('fogSensorReadout').textContent = `SCORE ${d.fog_sensor.toFixed(1)} • ${d.fog.toUpperCase()} • ${d.fog_auto ? 'AUTO' : 'MANUAL'}`;
  $('fogSensorReadout').className = 'pill ' + (d.fog_auto ? 'online' : 'paused');
  $('fogAutoBtn').textContent = 'AUTO: ' + (d.fog_auto ? 'ON' : 'OFF');
  $('systemState').textContent = d.running ? '● LIVE' : '● PAUSED';
  $('systemState').className = 'pill ' + (d.running ? 'online' : 'paused');
  $('pauseBtn').textContent = d.running ? 'Pause' : 'Resume';
}

function renderVehicleTable(d) {
  $('vehicleTable').innerHTML = Object.entries(d.vehicles).map(([vid, v]) => `
    <tr style="cursor:pointer" onclick="selectVehicle('${vid}')">
      <td>${vid}${selectedVehicle === vid ? ' ●' : ''}</td>
      <td>${esc(v.type)}</td>
      <td>${esc(v.status)}</td>
      <td>${v.speed} km/h</td>
      <td>${esc(v.node)}</td>
      <td>${v.risk}% ${esc(v.risk_status)}</td>
      <td>${v.connected ? '🟢' : '🔴'}</td>
    </tr>`).join('');
}

function renderSelected() {
  const box = $('selectedPanel');
  if (!selectedVehicle || !currentState || !currentState.vehicles[selectedVehicle]) {
    box.innerHTML = '<p class="hint">Click a vehicle on the map or table to see details and controls.</p>';
    return;
  }
  const v = currentState.vehicles[selectedVehicle];
  box.innerHTML = `
    <div class="metric-row"><span>Driver</span><b>${esc(v.driver.name)}</b></div>
    <div class="metric-row"><span>Status</span><b>${esc(v.status)}</b></div>
    <div class="metric-row"><span>Speed</span><b>${v.speed} km/h</b></div>
    <div class="metric-row"><span>Node</span><b>${esc(v.node)} → ${esc(v.destination)}</b></div>
    <div class="metric-row"><span>Risk</span><b>${v.risk}% ${esc(v.risk_status)}</b></div>
    <div class="metric-row"><span>Fuel / Battery</span><b>${v.fuel}% / ${v.battery}%</b></div>
    <div class="command-row" style="margin-top:10px;grid-template-columns:1fr auto">
      <input type="range" min="0" max="40" value="${v.speed}" onchange="setVehicleSpeed('${selectedVehicle}', this.value)">
      <span>${v.speed} km/h</span>
    </div>
    <div style="margin-top:8px">
      ${v.connected ? `<button onclick="disconnectVehicle('${selectedVehicle}')">Simulate Disconnect</button>` : `<button onclick="connectVehicle('${selectedVehicle}')">Reconnect</button>`}
    </div>`;
}

function renderEmergencyControl(d) {
  const e = d.emergency || {};
  $('emergencyControl').innerHTML = e.active
    ? `<div class="emergency-control-active"><b>🚨 EMERGENCY ACTIVE</b><span>${esc(e.vehicle || 'Fleet')} • ${esc(e.reason || '')}</span></div><button class="resolve-btn all-ok-btn" onclick="allOkDashboard()">✓ ALL OK — CLEAR ALL</button>`
    : `<div class="emergency-control-ready">🟢 No active Control Room emergency. <a class="nav-link" href="/emergency">Open Emergency Center</a></div>`;
  const pending = (d.driver_emergency_requests || []).filter(x => !x.handled);
  $('driverEmergencyRequests').innerHTML = pending.length
    ? pending.map(x => `<div class="driver-emergency-request"><div><b>🚨 ${esc(x.vehicle)} • ${esc(x.driver)}</b><small>${esc(x.time)}</small><p>${esc(x.reason)}</p></div><button class="resolve-btn" onclick="acknowledgeDriverEmergency('${x.vehicle}')">✓ ALL OK</button></div>`).join('')
    : '';
}

function renderQuickIncidents(d) {
  const active = (d.incidents || []).filter(x => x.active);
  $('quickIncidents').innerHTML = active.length
    ? active.map(x => `<div class="incident-mini"><span>${x.icon} ${esc(x.type.toUpperCase())} • ${esc(x.road)} • ${esc(x.time)}</span><b>${esc(x.severity)}</b><button onclick="clearQuickIncident(${x.id})">Resolve</button></div>`).join('')
    : '<p class="hint">No active incidents.</p>';
}

function renderV2V(d) {
  const vehicleIds = Object.keys(d.vehicles);
  for (const sel of [$('msgFrom'), $('msgTo')]) {
    const old = sel.value;
    sel.innerHTML = ['CTRL', ...vehicleIds].map(id => `<option value="${id}">${id}</option>`).join('');
    if (old && [...sel.options].some(o => o.value === old)) sel.value = old;
  }
  if ($('msgFrom').value === $('msgTo').value) $('msgTo').selectedIndex = 1;
  $('v2vInfo').innerHTML = (d.v2v || []).length
    ? (d.v2v || []).map(([a, b]) => `<div class="metric-row"><span>${a} ↔ ${b}</span><button onclick="disconnectV2V('${a}','${b}')">Unlink</button></div>`).join('')
    : '<p class="hint">No active V2V links.</p>';
  const now = Date.now() / 1000;
  const msgs = (d.messages || []).filter(m => m.expires_at > now);
  $('messages').innerHTML = msgs.length
    ? msgs.slice(0, 25).map(m => `<div class="message priority-${(m.level || 'info').toLowerCase()}"><b>${esc(m.from)} → ${esc(m.to)}</b> ${esc(m.message)}<em>${esc(m.time)}</em></div>`).join('')
    : '<p class="hint">No recent messages.</p>';
}

function renderAlerts(d) {
  const now = Date.now() / 1000;
  const alerts = (d.messages || []).filter(m => m.expires_at > now && m.level !== 'INFO');
  $('alerts').innerHTML = alerts.length
    ? alerts.slice(0, 15).map(m => `<div class="message priority-${m.level.toLowerCase()}"><b>${esc(m.from)} → ${esc(m.to)}</b> ${esc(m.message)}<em>${esc(m.time)}</em></div>`).join('')
    : '<p class="hint">No active alerts.</p>';
}

function renderRoute(d) {
  d = d || currentState;
  if (!d) return;
  if (!selectedVehicle || !d.vehicles[selectedVehicle]) {
    $('routeInfo').innerHTML = '<p class="hint">Select a vehicle to see its planned route.</p>';
    return;
  }
  const v = d.vehicles[selectedVehicle];
  $('routeInfo').innerHTML = `<div class="metric-row"><span>Vehicle</span><b>${selectedVehicle}</b></div>
    <div class="metric-row"><span>Path</span><b>${(v.route || []).join(' → ') || '—'}</b></div>
    <div class="metric-row"><span>Route cost</span><b>${v.route_cost ?? '—'}</b></div>`;
}

function renderEvents(d) {
  $('events').innerHTML = (d.events || []).slice(0, 30).map(x => `<div class="event"><span>${esc(x.time)}</span><b>${esc(x.kind)}</b> ${esc(x.message)}</div>`).join('') || '<p class="hint">No events yet.</p>';
}

function checkPopups(d) {
  for (const [vid, v] of Object.entries(d.vehicles)) {
    const was = prevConnected[vid];
    if (was === true && v.connected === false && !shownConnLostFor.has(vid)) {
      shownConnLostFor.add(vid);
      $('lostVehicle').textContent = vid;
      const lt = v.last_telemetry;
      $('lostLastInfo').textContent = lt ? `${lt.node} • ${lt.speed} km/h • fuel ${lt.fuel}% • battery ${lt.battery}% • ${lt.time}` : 'Last known information unavailable.';
      $('connectionLostPopup').classList.add('show'); $('connectionLostPopup').setAttribute('aria-hidden', 'false');
    }
    if (v.connected) shownConnLostFor.delete(vid);
    prevConnected[vid] = v.connected;
  }
  const pending = (d.driver_emergency_requests || []).filter(x => !x.handled);
  for (const req of pending) {
    if (!shownDriverRequestIds.has(req.id)) {
      shownDriverRequestIds.add(req.id);
      $('popupVehicle').textContent = req.vehicle;
      $('popupDriver').textContent = req.driver;
      $('popupReason').textContent = req.reason;
      $('driverEmergencyPopup').classList.add('show'); $('driverEmergencyPopup').setAttribute('aria-hidden', 'false');
    }
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    currentState = d;
    renderMap(d);
    renderKpis(d);
    renderAiSafety(d);
    renderEnvironment(d);
    renderVehicleTable(d);
    renderSelected();
    renderEmergencyControl(d);
    renderQuickIncidents(d);
    renderV2V(d);
    renderAlerts(d);
    renderRoute(d);
    renderEvents(d);
    checkPopups(d);
  } catch (e) { console.error(e); }
}

function clock() { $('clock').textContent = new Date().toLocaleTimeString(); }
setInterval(refresh, 700);
setInterval(clock, 1000);
clock();
refresh();
