/* FogSafe Driver dashboard logic */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

async function post(url, body = {}) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

let lang = localStorage.getItem('fogsafe-driver-language') || 'en';
let voiceOn = true;
let currentVehicle = localStorage.getItem('fogsafe-driver-vehicle') || null;
let currentState = null;
let shownMessageIds = new Set();
let emergencyTimer = null;
let emergencyCountdownValue = 3;

const I18N = {
  en: { control: 'Control Room', emergencyDash: 'Emergency', vehicle: 'MY VEHICLE', start: 'Start / Move', stop: 'Stop', idle: 'Idle', emergency: 'EMERGENCY', driver: 'DRIVER', truck: 'TRUCK', type: 'TYPE', speed: 'SPEED', location: 'LOCATION', safety: 'Safety Score', fog: '🌫️ Live Fog Conditions', safeSpeed: 'Safe speed', follow: 'Recommended following distance', health: 'Truck Health', fuel: 'Fuel', battery: 'Battery', communication: 'Communication', destination: 'Destination', route: 'Route Guidance', routeHint: 'Safest available route considers fog and road hazards.', v2v: 'Nearby V2V Connections', messages: 'Safety Messages', alerts: 'Driver Alerts', controlMessage: 'CONTROL ROOM MESSAGE', ack: 'Acknowledge', emergencyActive: 'EMERGENCY ACTIVE', focus: 'Stay focused and follow Control Room orders.' },
  hi: { control: 'कंट्रोल रूम', emergencyDash: 'आपातकाल', vehicle: 'मेरा वाहन', start: 'शुरू करें / चलें', stop: 'रोकें', idle: 'निष्क्रिय', emergency: 'आपातकाल', driver: 'ड्राइवर', truck: 'ट्रक', type: 'प्रकार', speed: 'गति', location: 'स्थान', safety: 'सुरक्षा स्कोर', fog: '🌫️ वर्तमान कोहरा स्थिति', safeSpeed: 'सुरक्षित गति', follow: 'अनुशंसित पीछा दूरी', health: 'ट्रक स्वास्थ्य', fuel: 'ईंधन', battery: 'बैटरी', communication: 'संचार', destination: 'गंतव्य', route: 'मार्ग मार्गदर्शन', routeHint: 'सुरक्षित मार्ग कोहरे और सड़क खतरों को ध्यान में रखता है।', v2v: 'नज़दीकी V2V कनेक्शन', messages: 'सुरक्षा संदेश', alerts: 'ड्राइवर अलर्ट', controlMessage: 'कंट्रोल रूम संदेश', ack: 'स्वीकार करें', emergencyActive: 'आपातकाल सक्रिय', focus: 'ध्यान केंद्रित रखें और कंट्रोल रूम के आदेशों का पालन करें।' },
  mr: { control: 'कंट्रोल रूम', emergencyDash: 'आणीबाणी', vehicle: 'माझे वाहन', start: 'सुरू करा / चला', stop: 'थांबा', idle: 'निष्क्रिय', emergency: 'आणीबाणी', driver: 'चालक', truck: 'ट्रक', type: 'प्रकार', speed: 'वेग', location: 'स्थान', safety: 'सुरक्षा गुण', fog: '🌫️ सद्य धुके स्थिती', safeSpeed: 'सुरक्षित वेग', follow: 'शिफारस केलेले पाठलाग अंतर', health: 'ट्रक आरोग्य', fuel: 'इंधन', battery: 'बॅटरी', communication: 'संपर्क', destination: 'गंतव्यस्थान', route: 'मार्ग मार्गदर्शन', routeHint: 'सुरक्षित मार्ग धुके आणि रस्ता धोके विचारात घेतो.', v2v: 'जवळील V2V जोडणी', messages: 'सुरक्षा संदेश', alerts: 'चालक सूचना', controlMessage: 'कंट्रोल रूम संदेश', ack: 'मान्य करा', emergencyActive: 'आणीबाणी सक्रिय', focus: 'लक्ष केंद्रित करा आणि कंट्रोल रूमच्या सूचनांचे पालन करा.' },
};
const VOICE_LOCALE = { en: 'en-US', hi: 'hi-IN', mr: 'mr-IN' };

function applyLanguage() {
  const sel = $('languageSelect');
  if (sel) sel.value = lang;
  const dict = I18N[lang] || I18N.en;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) el.textContent = dict[key];
  });
}

function speak(text) {
  if (!voiceOn || !('speechSynthesis' in window)) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = VOICE_LOCALE[lang] || 'en-US';
    window.speechSynthesis.speak(u);
  } catch (e) { /* voice not available */ }
}

function toggleVoice() {
  voiceOn = !voiceOn;
  $('voiceToggle').textContent = voiceOn ? '🔊 Voice ON' : '🔇 Voice OFF';
}

/* ---------- status controls ---------- */
function setStatus(status) {
  if (!currentVehicle || !currentState) return;
  const safe = currentState.safe_speed || 20;
  const speed = status === 'MOVING' ? safe : 0;
  post(`/api/speed/${currentVehicle}`, { speed }).then(refresh).catch(e => alert(e.message));
}

/* ---------- emergency modal ---------- */
function openEmergencyModal() {
  $('driverEmergencyReason').value = '';
  emergencyCountdownValue = 3;
  $('emergencyCountdown').textContent = emergencyCountdownValue;
  $('driverEmergencyInput').classList.add('show');
  $('driverEmergencyInput').setAttribute('aria-hidden', 'false');
  clearInterval(emergencyTimer);
  emergencyTimer = setInterval(() => {
    emergencyCountdownValue -= 1;
    $('emergencyCountdown').textContent = Math.max(emergencyCountdownValue, 0);
    if (emergencyCountdownValue <= 0) {
      clearInterval(emergencyTimer);
      emergencyTimer = null;
      autoFallbackEmergency();
    }
  }, 1000);
}

function closeEmergencyModalUI() {
  $('driverEmergencyInput').classList.remove('show');
  $('driverEmergencyInput').setAttribute('aria-hidden', 'true');
}

function cancelEmergencyModal() {
  clearInterval(emergencyTimer);
  emergencyTimer = null;
  closeEmergencyModalUI();
}

async function submitManualEmergency() {
  clearInterval(emergencyTimer);
  emergencyTimer = null;
  closeEmergencyModalUI();
  if (!currentVehicle) return;
  const reason = $('driverEmergencyReason').value.trim() || 'Driver emergency button pressed';
  try { await post('/api/emergency/driver', { vehicle: currentVehicle, reason }); refresh(); } catch (e) { alert(e.message); }
}

async function autoFallbackEmergency() {
  closeEmergencyModalUI();
  if (!currentVehicle) return;
  try {
    await post('/api/emergency/driver-auto', { vehicle: currentVehicle, reason: 'Driver unable to complete manual emergency input within 3 seconds' });
    refresh();
  } catch (e) { console.error(e); }
}

/* ---------- overlays ---------- */
function closeMessageOverlay() { $('messageOverlay').classList.remove('show'); $('messageOverlay').setAttribute('aria-hidden', 'true'); }

function showMessageOverlay(m) {
  $('overlayMessage').textContent = m.message;
  $('overlayMeta').textContent = `${m.from} → ${m.to} • ${m.time}`;
  $('messageOverlay').classList.add('show');
  $('messageOverlay').setAttribute('aria-hidden', 'false');
  speak(m.message);
  setTimeout(closeMessageOverlay, 9000);
}

/* ---------- render ---------- */
function populateVehicleSelect(d) {
  const sel = $('vehicleSelect');
  const ids = Object.keys(d.vehicles);
  if (!currentVehicle || !ids.includes(currentVehicle)) currentVehicle = ids[0];
  sel.innerHTML = ids.map(id => `<option value="${id}">${id} — ${esc(d.vehicles[id].driver.name)}</option>`).join('');
  sel.value = currentVehicle;
  sel.onchange = () => { currentVehicle = sel.value; localStorage.setItem('fogsafe-driver-vehicle', currentVehicle); render(); };
}

function render() {
  const d = currentState;
  if (!d || !currentVehicle || !d.vehicles[currentVehicle]) return;
  const v = d.vehicles[currentVehicle];

  $('driverName').textContent = v.driver.name;
  $('driverMeta').textContent = `${v.driver.shift} • ${v.driver.license} • ${v.driver.experience}`;
  $('statusBadge').textContent = v.status;
  $('statusBadge').className = 'status-badge ' + v.status.toLowerCase();
  $('truckId').textContent = currentVehicle;
  $('truckType').textContent = v.type;
  $('speed').textContent = v.speed + ' km/h';
  $('location').textContent = v.node;

  $('riskScore').textContent = v.risk + '%';
  $('riskBand').textContent = v.risk_status;
  $('riskBand').className = 'risk-band ' + v.risk_status.toLowerCase();
  $('safetyAdvice').textContent = v.risk_status === 'CRITICAL' || v.risk_status === 'HIGH'
    ? 'Reduce speed, increase following distance and stay alert.'
    : 'Conditions within normal parameters. Continue safe operation.';

  $('driverFog').textContent = d.fog.toUpperCase();
  $('driverFog').className = 'fog ' + d.fog;
  $('driverSafeSpeed').textContent = d.safe_speed + ' km/h';
  $('driverFollow').textContent = d.follow_distance + ' m';
  $('fogAdvice').textContent = d.fog === 'critical' ? 'Critical fog: proceed only at minimum safe speed.' : d.fog === 'dense' ? 'Dense fog: reduce speed and maximize following distance.' : 'Visibility acceptable. Maintain safe operating speed.';

  $('fuelBar').style.width = v.fuel + '%';
  $('fuel').textContent = v.fuel + '%';
  $('batteryBar').style.width = v.battery + '%';
  $('battery').textContent = v.battery + '%';
  $('comm').textContent = v.connected ? 'ONLINE' : 'OFFLINE';
  $('destination').textContent = v.destination;

  $('driverRoute').textContent = (v.route || []).join(' → ') || '—';

  const links = (d.v2v || []).filter(([a, b]) => a === currentVehicle || b === currentVehicle).map(([a, b]) => a === currentVehicle ? b : a);
  $('myLinks').innerHTML = links.length ? links.map(id => `<span class="pill online">${id}</span>`).join(' ') : '—';

  const now = Date.now() / 1000;
  const myMsgs = (d.messages || []).filter(m => (m.to === currentVehicle || m.from === currentVehicle) && m.expires_at > now);
  $('myMessages').innerHTML = myMsgs.length ? myMsgs.slice(0, 10).map(m => `<div class="message priority-${(m.level || 'info').toLowerCase()}"><b>${esc(m.from)} → ${esc(m.to)}</b> ${esc(m.message)}<em>${esc(m.time)}</em></div>`).join('') : '—';

  const myAlerts = (d.messages || []).filter(m => m.to === currentVehicle && m.expires_at > now && m.level !== 'INFO');
  $('driverAlerts').innerHTML = myAlerts.length ? myAlerts.slice(0, 10).map(m => `<div class="message priority-${m.level.toLowerCase()}">${esc(m.message)}<em>${esc(m.time)}</em></div>`).join('') : '—';

  const isEmergency = v.status === 'EMERGENCY';
  $('driverEmergencyStatus').textContent = isEmergency ? 'EMERGENCY ACTIVE' : 'NORMAL';
  $('driverEmergencyStatus').className = 'driver-emergency-status ' + (isEmergency ? 'active' : 'normal');

  if (isEmergency) {
    $('emergencyVehicleText').textContent = `${currentVehicle} — STOP VEHICLE`;
    $('emergencyAdvice').textContent = d.emergency && d.emergency.reason ? d.emergency.reason : 'Stay focused and follow Control Room orders.';
    $('emergencyOverlay').classList.add('show');
    $('emergencyOverlay').setAttribute('aria-hidden', 'false');
  } else {
    $('emergencyOverlay').classList.remove('show');
    $('emergencyOverlay').setAttribute('aria-hidden', 'true');
  }

  // Surface new control-room messages addressed to this vehicle as an overlay.
  const incoming = (d.messages || []).filter(m => m.to === currentVehicle && m.from === 'CTRL' && m.expires_at > now);
  for (const m of incoming) {
    if (!shownMessageIds.has(m.id)) {
      shownMessageIds.add(m.id);
      showMessageOverlay(m);
    }
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    currentState = d;
    populateVehicleSelect(d);
    render();
  } catch (e) { console.error(e); }
}

function clock() { $('clock').textContent = new Date().toLocaleTimeString(); }
setInterval(refresh, 700);
setInterval(clock, 1000);
clock();
refresh();
