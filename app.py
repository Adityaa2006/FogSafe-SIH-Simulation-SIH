from flask import Flask, render_template, jsonify, request
import heapq
import math
import random
import time
from collections import deque

app = Flask(__name__)

NODES = {
    "ENTRY": (50, 420), "N1": (200, 330), "N2": (350, 220),
    "N3": (350, 400), "N4": (520, 150), "N5": (520, 330),
    "N6": (700, 220), "PLANT": (850, 120)
}

ROADS = {
    ("ENTRY", "N1"): {"distance": 200, "fog": 20},
    ("N1", "N2"): {"distance": 220, "fog": 65},
    ("N1", "N3"): {"distance": 240, "fog": 20},
    ("N2", "N4"): {"distance": 180, "fog": 75},
    ("N2", "N5"): {"distance": 210, "fog": 45},
    ("N3", "N5"): {"distance": 170, "fog": 15},
    ("N4", "N6"): {"distance": 180, "fog": 70},
    ("N5", "N6"): {"distance": 160, "fog": 20},
    ("N6", "PLANT"): {"distance": 170, "fog": 10},
    ("N5", "PLANT"): {"distance": 280, "fog": 30},
}

FOG_MULTIPLIER = {"clear": 0.0, "moderate": 0.8, "dense": 1.8, "critical": 3.5}
SAFE_SPEED = {"clear": 30, "moderate": 20, "dense": 10, "critical": 5}
FOLLOW_DISTANCE = {"clear": 12, "moderate": 16, "dense": 22, "critical": 30}
FOG_SCORE = {"clear": 10, "moderate": 40, "dense": 70, "critical": 90}

# Fog detection sensor: a simulated 0-100 visibility-obstruction score that is
# mapped to an environment band. This stands in for a real IoT fog/visibility
# sensor (e.g. an optical transmissometer) feeding the Control Room.
FOG_SENSOR_RANGES = [
    ("clear", 0, 10),
    ("moderate", 10, 30),
    ("dense", 30, 60),
    ("critical", 60, 100),
]


def fog_level_from_score(score):
    for level, lo, hi in FOG_SENSOR_RANGES:
        if lo <= score < hi:
            return level
    return "critical" if score >= 100 else "clear"


def update_fog_sensor(dt):
    """Advance the simulated fog sensor with a slow, bounded random drift and
    occasional larger environmental shifts, then re-derive the fog level."""
    if not state.get("fog_auto", True):
        return
    sensor = state.get("fog_sensor", 5.0)
    # Slow baseline drift.
    drift = random.uniform(-1.2, 1.2) * max(dt, 0.05) * 2.0
    # Rare bigger swing (a fog bank rolling in/out) to keep the demo lively.
    if random.random() < 0.01:
        drift += random.uniform(-18, 18)
    sensor = max(0.0, min(100.0, sensor + drift))
    state["fog_sensor"] = round(sensor, 1)
    new_level = fog_level_from_score(sensor)
    if new_level != state["fog"]:
        old_level = state["fog"]
        state["fog"] = new_level
        log_event("ENVIRONMENT", f"Fog sensor auto-updated: {old_level.upper()} → {new_level.upper()} (score {sensor:.1f})")
        if new_level in ("dense", "critical"):
            for vid in state["vehicles"]:
                send_control(vid, f"Fog sensor alert: {new_level.upper()} (score {sensor:.0f}) - reduce speed and increase following distance.", "WARN")
AUTO_EMERGENCY_HOLD = 4.0
AUTO_EMERGENCY_MAX_DURATION = 20.0
AUTO_EMERGENCY_COOLDOWN = 18.0
AUTO_ESCAPE_DURATION = 2.5
YIELD_DURATION = 5.0
TRAFFIC_YIELD_COOLDOWN = 6.0

EMERGENCY_TYPES = {
    "collision": {"label": "Vehicle Collision", "icon": "💥", "severity": "CRITICAL", "action": "Stop affected vehicles, secure the area and dispatch emergency response."},
    "landslide": {"label": "Landslide", "icon": "⛰️", "severity": "CRITICAL", "action": "Block the affected road, stop approaching vehicles and recalculate a safe route."},
    "rockfall": {"label": "Rockfall", "icon": "🪨", "severity": "HIGH", "action": "Reduce speed, keep clear of the rockfall zone and reroute if required."},
    "flood": {"label": "Flooded Road", "icon": "🌊", "severity": "CRITICAL", "action": "Close the flooded road and redirect vehicles to a safe route."},
    "fire": {"label": "Vehicle / Site Fire", "icon": "🔥", "severity": "CRITICAL", "action": "Stop nearby traffic and activate fire-response procedures."},
    "breakdown": {"label": "Vehicle Breakdown", "icon": "🔧", "severity": "HIGH", "action": "Protect the stopped vehicle and keep approaching traffic at a safe distance."},
    "medical": {"label": "Medical Emergency", "icon": "🚑", "severity": "CRITICAL", "action": "Request medical assistance and keep the vehicle stopped in a safe location."},
    "severe_fog": {"label": "Severe Fog", "icon": "🌫️", "severity": "HIGH", "action": "Reduce speed, increase following distance and use the safest available route."},
    "road_obstruction": {"label": "Road Obstruction", "icon": "🚧", "severity": "HIGH", "action": "Block the affected section and reroute vehicles."},
}

DRIVER_INFO = {
    "V01": {"name": "Rajesh Patil", "shift": "Day Shift", "license": "HT-2041", "phone": "+91 90000 10001", "experience": "8 years"},
    "V02": {"name": "Amit Shinde", "shift": "Day Shift", "license": "WT-1872", "phone": "+91 90000 10002", "experience": "6 years"},
    "V03": {"name": "Suresh Jadhav", "shift": "Day Shift", "license": "EX-3310", "phone": "+91 90000 10003", "experience": "10 years"},
    "V04": {"name": "Vijay More", "shift": "Night Shift", "license": "ST-2298", "phone": "+91 90000 10004", "experience": "5 years"},
}

VEHICLE_TYPES = {"V01": "Haul Truck", "V02": "Water Tanker", "V03": "Excavator", "V04": "Service Truck"}

# V02 is intentionally travelling back toward ENTRY so the demo can show
# an opposite-direction encounter with V01 on N1-N2.
INITIAL_VEHICLES = {
    "V01": {"node": "N1", "speed": 24, "distance": 25, "connected": True, "destination": "PLANT", "status": "MOVING", "fuel": 82, "battery": 91},
    "V02": {"node": "N2", "speed": 24, "distance": 18, "connected": True, "destination": "ENTRY", "status": "MOVING", "fuel": 68, "battery": 86},
    "V03": {"node": "N3", "speed": 0, "distance": 8, "connected": True, "destination": "PLANT", "status": "STOPPED", "fuel": 54, "battery": 74},
    "V04": {"node": "N4", "speed": 9, "distance": 30, "connected": True, "destination": "PLANT", "status": "MOVING", "fuel": 73, "battery": 88},
}


def fresh_vehicles():
    return {k: {**v, "progress": 0.0, "route_index": 0, "manual_status": None, "current_edge": None, "yield_until": 0.0, "traffic_yield": False} for k, v in INITIAL_VEHICLES.items()}


state = {
    "fog": "clear",
    "fog_sensor": 5.0,
    "fog_auto": True,
    "emergency": {"active": False, "source": None, "vehicle": None, "type": None, "type_label": None, "reason": "", "started_at": None, "cleared_at": None},
    "driver_emergency_requests": deque(maxlen=20),
    "incidents": deque(maxlen=30),
    "incident_seq": 0,
    "hazards": set(),
    "vehicles": fresh_vehicles(),
    "v2v": {("V01", "V02"), ("V02", "V03"), ("V03", "V04")},
    "messages": deque(maxlen=60),
    "events": deque(maxlen=70),
    "road_conflicts": {},
    "auto_emergencies": {},
    "auto_cooldowns": {},
    "traffic_yields": {},
    "message_seq": 0,
    "running": True,
    "last_tick": time.time(),
}


def road_key(a, b):
    return "-".join(sorted([a, b]))


def edge_data(a, b):
    return ROADS.get((a, b)) or ROADS.get((b, a))


def log_event(kind, message):
    state["events"].appendleft({"time": time.strftime("%H:%M:%S"), "kind": kind, "message": message})


def add_message(sender, receiver, message, level="INFO", ttl=8):
    state["message_seq"] += 1
    now = time.time()
    msg = {
        "id": state["message_seq"],
        "time": time.strftime("%H:%M:%S"),
        "created_at": now,
        "expires_at": now + ttl,
        "from": sender,
        "to": receiver,
        "message": message[:220],
        "level": level,
    }
    state["messages"].appendleft(msg)
    return msg


def send_v2v(sender, receiver, message, level="INFO"):
    pair = tuple(sorted((sender, receiver)))
    if pair not in state["v2v"]:
        return False
    add_message(sender, receiver, message, level, 8 if level == "INFO" else 10)
    return True


def activate_control_emergency(vid, reason="Control Room emergency command", incident_type="collision"):
    if vid not in state["vehicles"]:
        return False
    v = state["vehicles"][vid]
    v["manual_status"] = "EMERGENCY"
    v["status"] = "EMERGENCY"
    v["speed"] = 0
    type_info = EMERGENCY_TYPES.get(incident_type, EMERGENCY_TYPES["collision"])
    state["emergency"] = {"active": True, "source": "CONTROL", "vehicle": vid, "type": incident_type, "type_label": type_info["label"], "reason": reason[:180], "started_at": time.time(), "cleared_at": None}
    send_control(vid, f"CONTROL ROOM EMERGENCY: STOP NOW. {reason[:120]}. Stay focused and follow Control Room orders.", "CRITICAL")
    for a, b in list(state["v2v"]):
        if a == vid:
            send_v2v(a, b, "CONTROL ROOM EMERGENCY: keep safe distance and await instructions", "CRITICAL")
        elif b == vid:
            send_v2v(b, a, "CONTROL ROOM EMERGENCY: keep safe distance and await instructions", "CRITICAL")
    log_event("CONTROL_EMERGENCY", f"Control Room activated emergency for {vid}: {reason[:100]}")
    return True


def clear_all_emergency(reason="ALL OK - situation under control"):
    changed = False
    affected = []
    for vid, v in state["vehicles"].items():
        if v.get("status") == "EMERGENCY" or v.get("manual_status") == "EMERGENCY":
            # ALL OK releases the truck back to normal travel.
            v["manual_status"] = None
            v["emergency_mode"] = None
            v["status"] = "MOVING" if v["connected"] and v["node"] != v["destination"] else "ARRIVED"
            v["speed"] = min(max(v["speed"], 1), SAFE_SPEED[state["fog"]]) if v["status"] == "MOVING" else 0
            affected.append(vid)
            changed = True
    if state["auto_emergencies"]:
        state["auto_emergencies"].clear()
        changed = True
    if state["emergency"].get("active") or affected:
        for vid in affected:
            send_control(vid, "ALL OK: Situation is under control. Continue travel at a safe speed and follow Control Room instructions.", "WARN")
        state["emergency"]["cleared_at"] = time.time()
        log_event("EMERGENCY_CLEAR", f"ALL OK: emergency cleared for {', '.join(affected) if affected else 'fleet'}")
        state["emergency"] = {"active": False, "source": None, "vehicle": None, "type": None, "type_label": None, "reason": "", "started_at": None, "cleared_at": time.time()}
    return changed


def request_driver_emergency(vid, reason="Driver emergency button pressed"):
    if vid not in state["vehicles"]:
        return False
    v = state["vehicles"][vid]
    v["manual_status"] = "EMERGENCY"
    v["status"] = "EMERGENCY"
    v["speed"] = 0
    req = {"id": state["message_seq"] + 1, "vehicle": vid, "driver": DRIVER_INFO[vid]["name"], "reason": reason[:180], "time": time.strftime("%H:%M:%S"), "created_at": time.time(), "handled": False}
    state["driver_emergency_requests"].appendleft(req)
    add_message(vid, "CTRL", f"DRIVER EMERGENCY REQUEST: {reason[:140]}", "CRITICAL", 18)
    log_event("DRIVER_EMERGENCY", f"{vid} driver emergency request received: {reason[:100]}")
    return True


def send_control(receiver, message, level="WARN"):
    if receiver not in state["vehicles"]:
        return False
    ttl = 9 if level == "WARN" else 12
    add_message("CTRL", receiver, message, level, ttl)
    log_event("CONTROL", f"Control Room message sent to {receiver}: {message[:80]}")
    return True


def heuristic(node, goal):
    x, y = NODES[node]
    gx, gy = NODES[goal]
    return math.hypot(x - gx, y - gy)


def astar(start, goal):
    pq = [(heuristic(start, goal), 0, start)]
    came_from, g_score = {start: None}, {start: 0}
    while pq:
        _, current_g, current = heapq.heappop(pq)
        if current == goal:
            path, n = [], current
            while n is not None:
                path.append(n)
                n = came_from[n]
            return path[::-1], current_g
        if current_g != g_score[current]:
            continue
        for (a, b), data in ROADS.items():
            if a == current:
                nxt = b
            elif b == current:
                nxt = a
            else:
                continue
            if road_key(current, nxt) in state["hazards"]:
                continue
            dynamic_cost = data["distance"] * (1 + (data["fog"] / 100.0) * FOG_MULTIPLIER[state["fog"]])
            new_g = current_g + dynamic_cost
            if new_g < g_score.get(nxt, float("inf")):
                g_score[nxt] = new_g
                came_from[nxt] = current
                heapq.heappush(pq, (new_g + heuristic(nxt, goal), new_g, nxt))
    return [], float("inf")


def calculate_risk(v):
    fog = state["fog"]
    risk = FOG_SCORE[fog]
    if v["speed"] > SAFE_SPEED[fog]:
        risk += 15
    if v["distance"] < FOLLOW_DISTANCE[fog]:
        risk += 15
    if not v["connected"]:
        risk += 25
    if v["status"] in ("EMERGENCY", "BREAKDOWN"):
        risk += 25
    if v["fuel"] < 20:
        risk += 10
    if v["battery"] < 20:
        risk += 10
    risk = min(100, risk)
    if risk < 30:
        status = "SAFE"
    elif risk < 50:
        status = "CAUTION"
    elif risk < 75:
        status = "HIGH"
    else:
        status = "CRITICAL"
    return risk, status


def route_for(v):
    return astar(v["node"], v["destination"])


def vehicle_motion(v):
    """Return smooth position using a persistent directed edge.
    Keeping the current edge prevents route recalculation from making a vehicle
    jump or oscillate backwards while it is already travelling between nodes.
    """
    edge = v.get("current_edge")
    if edge:
        a, b = edge
        if edge_data(a, b) and a != b:
            ratio = min(1.0, max(0.0, v.get("progress", 0.0) / max(edge_data(a, b)["distance"], 1)))
            x1, y1 = NODES[a]
            x2, y2 = NODES[b]
            return x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio, (a, b), ratio
    x, y = NODES[v["node"]]
    return x, y, None, 0.0


def trigger_auto_emergency(vid, reason):
    """Yield one vehicle for an opposite-direction encounter.
    The other vehicle continues moving. A single common instruction is issued
    for the encounter; after the vehicles pass, only one ALL OK message is sent.
    """
    if vid not in state["vehicles"]:
        return False
    now = time.time()
    v = state["vehicles"][vid]
    if not v["connected"] or v["status"] in ("EMERGENCY", "MAINTENANCE", "OFFLINE"):
        return False

    # Do not re-trigger the same encounter.
    if v.get("traffic_yield"):
        return False

    v["yield_until"] = now + 30.0  # safety fallback; normal clearance releases it earlier
    v["traffic_yield"] = True
    v["status"] = "STOPPED"
    v["speed"] = 0
    state.setdefault("traffic_yields", {})[vid] = {
        "vehicle": vid, "started_at": now, "reason": reason[:180]
    }
    # One common instruction only; no per-vehicle duplicate warnings.
    state.setdefault("traffic_instruction_active", set()).add(
        tuple(sorted(next((c["vehicles"] for c in state["road_conflicts"].values() if vid in c["vehicles"]), [vid])))
    )
    log_event("TRAFFIC_YIELD", f"{vid} yielded for opposite-direction traffic")
    return True


def _clear_auto_emergency(vid, reason="traffic separation restored"):
    v = state["vehicles"].get(vid)
    if not v:
        return False
    v["traffic_yield"] = False
    v["yield_until"] = 0.0
    state.get("traffic_yields", {}).pop(vid, None)
    if v.get("manual_status") is None and v.get("connected") and v.get("node") != v.get("destination"):
        v["status"] = "MOVING"
        v["speed"] = min(SAFE_SPEED[state["fog"]], max(1, v.get("speed", 0)))
    log_event("TRAFFIC_RESUME", f"{vid} resumed after traffic separation was restored")
    return True


def evaluate_ai_safety(conflicts):
    now = time.time()
    # Pick one vehicle to yield for each active encounter. The other vehicle
    # keeps moving so the crossing cannot deadlock.
    for conflict in conflicts:
        if conflict["gap"] <= 70:
            a, b = conflict["vehicles"]
            candidates = [x for x in (a, b) if state["vehicles"][x].get("manual_status") is None
                          and state["vehicles"][x].get("connected") and not state["vehicles"][x].get("traffic_yield")]
            if candidates:
                # Yield the vehicle that is farther from its edge end (stable rule).
                vid = candidates[-1]
                trigger_auto_emergency(vid, f"Opposite-direction traffic on {conflict['road']}")

    # Critical fog remains a safety stop.
    if state["fog"] == "critical":
        for vid, v in state["vehicles"].items():
            if v["connected"] and v["status"] not in ("EMERGENCY", "MAINTENANCE", "OFFLINE"):
                if v.get("speed", 0) > SAFE_SPEED["critical"] + 4:
                    v["status"] = "STOPPED"
                    v["speed"] = 0
                    add_message("AI SAFETY", vid, "Critical fog: vehicle stopped automatically until visibility is safe.", "WARN", 6)

    # Clearance is based on actual map gap, not merely whether the stopped
    # vehicle is absent from the moving-vehicle list.
    for vid in list(state.get("traffic_yields", {})):
        v = state["vehicles"].get(vid)
        if not v:
            state["traffic_yields"].pop(vid, None)
            continue
        related = [c for c in conflicts if vid in c["vehicles"]]
        clear = not related or min(c["gap"] for c in related) >= 95
        if clear or now >= v.get("yield_until", 0):
            _clear_auto_emergency(vid)


def detect_opposite_direction_conflicts():
    """Detect opposite-direction vehicles using their persistent map edges.
    Includes temporarily stopped/yielding vehicles so the passing event remains
    visible until they have actually separated.
    """
    active = {}
    moving = []
    for vid, v in state["vehicles"].items():
        if not v["connected"] or v["status"] in ("EMERGENCY", "MAINTENANCE", "OFFLINE"):
            continue
        _, _, edge, ratio = vehicle_motion(v)
        if edge:
            moving.append((vid, edge, ratio))

    for i in range(len(moving)):
        for j in range(i + 1, len(moving)):
            va, edge_a, ra = moving[i]
            vb, edge_b, rb = moving[j]
            same_road = {edge_a[0], edge_a[1]} == {edge_b[0], edge_b[1]}
            opposite = edge_a[0] == edge_b[1] and edge_a[1] == edge_b[0]
            if not (same_road and opposite):
                continue
            data = edge_data(*edge_a)
            gap = abs((1.0 - ra) - rb) * data["distance"]
            if gap <= 220:
                key = "|".join(sorted([va, vb])) + "@" + road_key(*edge_a)
                severity = "CRITICAL" if gap <= 55 else "HIGH"
                active[key] = {"vehicles": sorted([va, vb]), "road": road_key(*edge_a), "gap": round(max(0, gap), 1), "severity": severity}

    old_keys = set(state["road_conflicts"])
    for key, info in active.items():
        if key not in old_keys:
            a, b = info["vehicles"]
            road = info["road"]
            # One common instruction represented by a single message to each
            # involved dashboard, with identical wording.
            common = "TRAFFIC INSTRUCTION: Slow down and maintain safe separation while vehicles pass."
            send_v2v(a, b, common, "WARN")
            send_v2v(b, a, common, "WARN")
            add_message("AI", "CTRL", f"{a} and {b} approaching on {road}. Gap {info['gap']} m.", "WARN", 8)
            log_event("TRAFFIC", f"Opposite-direction traffic: {a} ↔ {b} on {road} (gap {info['gap']} m)")

    for key in old_keys - set(active):
        info = state["road_conflicts"].get(key)
        if info:
            pair = tuple(sorted(info["vehicles"]))
            # Only emit the requested single final message, and only once.
            if not state.get("traffic_clear_sent", {}).get(pair):
                state.setdefault("traffic_clear_sent", {})[pair] = time.time()
                for vid in pair:
                    send_control(vid, "ALL OK: Traffic clear. Move forward.", "WARN")
                log_event("TRAFFIC_CLEAR", f"Traffic clear: {info['road']} between {' ↔ '.join(info['vehicles'])}")

    # Forget old clear markers when a new encounter starts.
    for key, info in active.items():
        state.setdefault("traffic_clear_sent", {}).pop(tuple(sorted(info["vehicles"])), None)

    state["road_conflicts"] = active
    evaluate_ai_safety(list(active.values()))


def advance_simulation():
    now = time.time()
    dt = min(now - state["last_tick"], 0.5)
    state["last_tick"] = now
    if not state["running"] or dt <= 0:
        detect_opposite_direction_conflicts()
        return

    update_fog_sensor(dt)

    for vid, v in state["vehicles"].items():
        if not v["connected"] or v["manual_status"] in ("EMERGENCY", "BREAKDOWN", "MAINTENANCE", "OFFLINE"):
            continue

        # Temporary yielding is a stop, not a reverse movement.
        if v.get("yield_until", 0) > now:
            v["status"] = "STOPPED"
            v["speed"] = 0
            continue
        elif v.get("yield_until"):
            v["yield_until"] = 0.0
            v["traffic_yield"] = False
            state.get("traffic_yields", {}).pop(vid, None)

        # If we are not currently on an edge, choose the next edge from A*.
        edge = v.get("current_edge")
        if not edge or edge[0] != v["node"] or not edge_data(*edge):
            path, _ = route_for(v)
            if len(path) < 2:
                v["status"] = "ARRIVED" if v["node"] == v["destination"] else "NO_ROUTE"
                v["speed"] = 0
                v["current_edge"] = None
                continue
            v["current_edge"] = (path[0], path[1])
            v["progress"] = 0.0
            edge = v["current_edge"]

        target = min(v["speed"] if v["speed"] > 0 else SAFE_SPEED[state["fog"]], SAFE_SPEED[state["fog"]])
        if state["fog"] == "critical":
            target = min(target, 5)
        v["speed"] = round(max(0, target), 1)
        v["status"] = "MOVING" if v["speed"] > 0 else "STOPPED"

        v["progress"] += v["speed"] * 1000 / 3600 * dt
        edge_distance = edge_data(*v["current_edge"])["distance"]
        while v["progress"] >= edge_distance:
            a, b = v["current_edge"]
            v["progress"] -= edge_distance
            v["node"] = b
            v["current_edge"] = None
            if v["node"] == v["destination"]:
                v["status"] = "ARRIVED"
                v["speed"] = 0
                v["progress"] = 0
                log_event("ARRIVAL", f"{vid} reached {v['destination']}")
                break
            # Pick the next safe edge only after reaching the node. This makes
            # A* rerouting stable instead of changing the meaning of progress.
            path, _ = route_for(v)
            if len(path) < 2:
                v["status"] = "NO_ROUTE"
                v["speed"] = 0
                break
            v["current_edge"] = (path[0], path[1])
            edge_distance = edge_data(*v["current_edge"])["distance"]

        v["fuel"] = round(max(0, v["fuel"] - dt * max(v["speed"], 1) / 360000), 1)
        v["battery"] = round(max(0, v["battery"] - dt * 0.003), 1)

    detect_opposite_direction_conflicts()


def snapshot():
    advance_simulation()
    now = time.time()
    # Messages stay in the server log, but expired messages are no longer sent
    # to the driver overlay/list. This prevents stale alerts from sticking.
    live_messages = [m for m in state["messages"] if m["expires_at"] > now]
    result = {
        "fog": state["fog"],
        "fog_sensor": state.get("fog_sensor", 0.0),
        "fog_auto": state.get("fog_auto", True),
        "safe_speed": SAFE_SPEED[state["fog"]],
        "follow_distance": FOLLOW_DISTANCE[state["fog"]],
        "hazards": sorted(state["hazards"]),
        "running": state["running"],
        "timestamp": int(now),
        "vehicles": {},
        "v2v": [list(pair) for pair in sorted(state["v2v"])],
        "messages": live_messages,
        "events": list(state["events"]),
        "road_conflicts": list(state["road_conflicts"].values()),
        "auto_emergencies": list(state["auto_emergencies"].values()),
        "emergency": {**state["emergency"], "started_at": int(state["emergency"]["started_at"]) if state["emergency"].get("started_at") else None, "cleared_at": int(state["emergency"]["cleared_at"]) if state["emergency"].get("cleared_at") else None},
        "driver_emergency_requests": list(state["driver_emergency_requests"]),
        "emergency_types": EMERGENCY_TYPES,
        "incidents": list(state["incidents"]),
    }
    for vid, v in state["vehicles"].items():
        risk, risk_status = calculate_risk(v)
        path, cost = route_for(v)
        x, y, edge, ratio = vehicle_motion(v)
        result["vehicles"][vid] = {
            **v,
            "type": VEHICLE_TYPES[vid],
            "risk": risk,
            "risk_status": risk_status,
            "route": path,
            "route_cost": None if not math.isfinite(cost) else round(cost, 1),
            "map_x": round(x, 2),
            "map_y": round(y, 2),
            "current_edge": list(edge) if edge else None,
            "edge_ratio": round(ratio, 3),
            "last_update": int(now),
            "driver": DRIVER_INFO[vid],
            "last_telemetry": v.get("last_telemetry"),
        }
    return result


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.get("/driver")
def driver_dashboard():
    return render_template("driver.html")


@app.get("/emergency")
def emergency_dashboard():
    return render_template("emergency.html")


@app.get("/api/state")
def api_state():
    return jsonify(snapshot())


@app.post("/api/fog")
def api_fog():
    """Manual override. Switches the fog sensor to manual mode and applies
    the requested level directly. Use /api/fog/auto to hand control back to
    the automatic sensor."""
    level = request.json.get("fog", "clear")
    if level not in FOG_MULTIPLIER:
        return jsonify({"error": "Invalid fog level"}), 400
    state["fog_auto"] = False
    state["fog"] = level
    lo, hi = next(((lo, hi) for lvl, lo, hi in FOG_SENSOR_RANGES if lvl == level), (0, 10))
    state["fog_sensor"] = round((lo + min(hi, 100) - 1) / 2, 1) if hi < 100 else round((lo + 100) / 2, 1)
    log_event("ENVIRONMENT", f"Fog manually overridden to {level.upper()} (auto-sensor disabled)")
    if level in ("dense", "critical"):
        for vid in state["vehicles"]:
            send_control(vid, f"Fog alert: {level.upper()} - reduce speed and increase following distance.", "WARN")
    return jsonify(snapshot())


@app.post("/api/fog/auto")
def api_fog_auto():
    """Toggle automatic fog-sensor mode on/off."""
    auto = bool(request.json.get("auto", True))
    state["fog_auto"] = auto
    log_event("ENVIRONMENT", "Fog sensor set to AUTOMATIC mode" if auto else "Fog sensor set to MANUAL mode")
    return jsonify(snapshot())


@app.post("/api/disconnect/<vid>")
def api_disconnect(vid):
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    v = state["vehicles"][vid]
    # Capture telemetry BEFORE changing the vehicle to OFFLINE.
    last = {
        "time": time.strftime("%H:%M:%S"),
        "timestamp": int(time.time()),
        "node": v["node"],
        "speed": v["speed"],
        "status": v["status"],
        "fuel": v["fuel"],
        "battery": v["battery"],
        "destination": v["destination"],
        "fog": state["fog"],
        "risk": calculate_risk(v)[0],
    }
    v["last_telemetry"] = last
    v["connected"] = False
    v["speed"] = 0
    v["status"] = "OFFLINE"
    v["manual_status"] = "OFFLINE"
    add_message(vid, "CTRL", (
        f"COMMUNICATION LOST. Last known information: location {last['node']}, "
        f"speed {last['speed']} km/h, status {last['status']}, fuel {last['fuel']}%, "
        f"battery {last['battery']}%, destination {last['destination']}, "
        f"fog {last['fog'].upper()}, risk {last['risk']}%."
    ), "CRITICAL", 30)
    log_event("COMMUNICATION", (
        f"{vid} lost communication at {last['time']} — last known location {last['node']}, "
        f"speed {last['speed']} km/h, fuel {last['fuel']}%, battery {last['battery']}%, "
        f"destination {last['destination']}, fog {last['fog'].upper()}, risk {last['risk']}%"
    ))
    return jsonify(snapshot())


@app.post("/api/connect/<vid>")
def api_connect(vid):
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    v = state["vehicles"][vid]
    v["connected"] = True
    v["manual_status"] = None
    if v["node"] != v["destination"]:
        v["status"] = "STOPPED"
    add_message("CTRL", vid, "Communication restored. Last known telemetry is available in Control Room. Verify vehicle condition before continuing.", "INFO", 10)
    log_event("COMMUNICATION", f"{vid} communication restored")
    return jsonify(snapshot())


@app.post("/api/status/<vid>")
def api_status(vid):
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    status = request.json.get("status", "MOVING").upper()
    allowed = {"MOVING", "STOPPED", "IDLE", "EMERGENCY", "MAINTENANCE"}
    if status not in allowed:
        return jsonify({"error": "Invalid status"}), 400
    v = state["vehicles"][vid]
    if status == "MOVING":
        v["manual_status"] = None
        if v["connected"]:
            v["speed"] = min(max(v["speed"], 1), SAFE_SPEED[state["fog"]])
    else:
        v["manual_status"] = status
        v["speed"] = 0
    v["status"] = status
    log_event("VEHICLE", f"{vid} status changed to {status}")
    if status == "EMERGENCY":
        request_driver_emergency(vid, "Driver activated emergency")
        for a, b in list(state["v2v"]):
            if a == vid:
                send_v2v(a, b, "DRIVER EMERGENCY: keep safe distance and await Control Room instructions", "CRITICAL")
            elif b == vid:
                send_v2v(b, a, "DRIVER EMERGENCY: keep safe distance and await Control Room instructions", "CRITICAL")
    return jsonify(snapshot())


@app.post("/api/emergency/incident")
def api_emergency_incident():
    data = request.json or {}
    incident_type = data.get("type", "road_obstruction")
    if incident_type not in EMERGENCY_TYPES:
        return jsonify({"error": "Invalid emergency type"}), 400
    road = data.get("road") or ""
    if road and "-" in road:
        a, b = road.split("-", 1)
        if not edge_data(a, b):
            return jsonify({"error": "Invalid road"}), 400
        state["hazards"].add(road_key(a, b))
    info = EMERGENCY_TYPES[incident_type]
    state["incident_seq"] += 1
    incident = {
        "id": state["incident_seq"],
        "type": incident_type,
        "label": info["label"],
        "icon": info["icon"],
        "severity": info["severity"],
        "road": road_key(a, b) if road and "-" in road else (road or "Fleet / Site"),
        "reason": (data.get("reason") or info["action"])[:180],
        "action": info["action"],
        "created_at": time.time(),
        "time": time.strftime("%H:%M:%S"),
        "active": True,
    }
    state["incidents"].appendleft(incident)
    log_event("EMERGENCY_INCIDENT", f"{info['label']} reported at {incident['road']}")
    for vid, v in state["vehicles"].items():
        if not v["connected"]:
            continue
        if road:
            send_control(vid, f"BAD ROAD: {incident['road']}. DO NOT ENTER. {info['label']}. Follow the recalculated safe route.", "CRITICAL")
        else:
            send_control(vid, f"{info['icon']} {info['label']}: {incident['road']}. {info['action']}", info["severity"])
    # A site/road incident is an emergency event, but it does not freeze the
    # entire fleet. Only affected roads are blocked and routes are recalculated.
    state["emergency"] = {"active": True, "source": "INCIDENT", "vehicle": None, "reason": f"{info['label']} at {incident['road']}", "started_at": time.time(), "cleared_at": None}
    return jsonify(snapshot())


@app.post("/api/emergency/incident/clear/<int:incident_id>")
def api_clear_incident(incident_id):
    found = False
    for incident in state["incidents"]:
        if incident["id"] == incident_id and incident.get("active"):
            incident["active"] = False
            found = True
            road = incident.get("road", "")
            if road and road in state["hazards"]:
                state["hazards"].discard(road)
            log_event("EMERGENCY_INCIDENT_CLEAR", f"Incident {incident_id} cleared: {incident['label']}")
            break
    if not found:
        return jsonify({"error": "Active incident not found"}), 404
    if not any(i.get("active") for i in state["incidents"]):
        if not state.get("auto_emergencies") and not any(v.get("status") == "EMERGENCY" for v in state["vehicles"].values()):
            state["emergency"] = {"active": False, "source": None, "vehicle": None, "type": None, "type_label": None, "reason": "", "started_at": None, "cleared_at": time.time()}
    return jsonify(snapshot())


@app.post("/api/emergency/control")
def api_control_emergency():
    vid = request.json.get("vehicle")
    reason = request.json.get("reason", "Control Room emergency command")
    incident_type = request.json.get("type", "collision")
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    if incident_type not in EMERGENCY_TYPES:
        incident_type = "collision"
    type_info = EMERGENCY_TYPES[incident_type]
    activate_control_emergency(vid, reason or type_info["action"], incident_type)
    return jsonify(snapshot())


@app.post("/api/emergency/driver")
def api_driver_emergency():
    vid = request.json.get("vehicle")
    reason = request.json.get("reason", "Driver emergency button pressed")
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    request_driver_emergency(vid, reason)
    return jsonify(snapshot())


@app.post("/api/emergency/driver-auto")
def api_driver_auto_emergency():
    vid = request.json.get("vehicle")
    reason = request.json.get("reason", "Driver unable to complete manual emergency input within 3 seconds")
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    # Automatic fallback is a driver-originated safety escalation, not an AI
    # hazard detection event. The Control Room still receives it immediately.
    request_driver_emergency(vid, reason)
    v = state["vehicles"][vid]
    v["emergency_mode"] = "DRIVER_AUTO_FALLBACK"
    add_message("AI SAFETY", "CTRL", f"DRIVER AUTO-EMERGENCY: {vid} — emergency input not completed within 3 seconds.", "CRITICAL", 18)
    log_event("DRIVER_AUTO_EMERGENCY", f"3-second fallback activated for {vid}")
    return jsonify(snapshot())


@app.post("/api/emergency/all-ok")
def api_all_ok():
    clear_all_emergency()
    for req in state["driver_emergency_requests"]:
        req["handled"] = True
    for incident in state["incidents"]:
        if incident.get("active"):
            incident["active"] = False
    state["hazards"].clear()
    state["emergency"] = {"active": False, "source": None, "vehicle": None, "type": None, "type_label": None, "reason": "", "started_at": None, "cleared_at": time.time()}
    log_event("EMERGENCY_CLEAR", "ALL OK: all emergency incidents and hazards cleared")
    return jsonify(snapshot())


@app.post("/api/emergency/clear/<vid>")
def api_clear_emergency(vid):
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    v = state["vehicles"][vid]
    if v["status"] == "EMERGENCY":
        v["manual_status"] = None
        v["emergency_mode"] = None
        v["status"] = "MOVING" if v["connected"] and v["node"] != v["destination"] else "ARRIVED"
        v["speed"] = min(max(v["speed"], 1), SAFE_SPEED[state["fog"]]) if v["status"] == "MOVING" else 0
        send_control(vid, "ALL OK: Situation is under control. Continue travel at a safe speed and follow Control Room instructions.", "WARN")
        log_event("EMERGENCY_CLEAR", f"{vid} emergency cleared by Control Room")
    if state["emergency"].get("vehicle") == vid:
        state["emergency"] = {"active": False, "source": None, "vehicle": None, "type": None, "type_label": None, "reason": "", "started_at": None, "cleared_at": time.time()}
    for req in state["driver_emergency_requests"]:
        if req["vehicle"] == vid:
            req["handled"] = True
    return jsonify(snapshot())


@app.post("/api/speed/<vid>")
def api_speed(vid):
    if vid not in state["vehicles"]:
        return jsonify({"error": "Unknown vehicle"}), 404
    speed = max(0, min(40, float(request.json.get("speed", 0))))
    v = state["vehicles"][vid]
    v["speed"] = speed
    v["manual_status"] = None
    v["status"] = "MOVING" if speed > 0 else "STOPPED"
    return jsonify(snapshot())


@app.post("/api/v2v/connect")
def api_v2v_connect():
    a, b = request.json.get("a"), request.json.get("b")
    if a not in state["vehicles"] or b not in state["vehicles"] or a == b:
        return jsonify({"error": "Invalid vehicle pair"}), 400
    state["v2v"].add(tuple(sorted((a, b))))
    send_v2v(a, b, f"{a} ↔ {b} V2V link established", "INFO")
    log_event("V2V", f"V2V link established: {a} ↔ {b}")
    return jsonify(snapshot())


@app.post("/api/v2v/disconnect")
def api_v2v_disconnect():
    a, b = request.json.get("a"), request.json.get("b")
    pair = tuple(sorted((a, b)))
    state["v2v"].discard(pair)
    log_event("V2V", f"V2V link removed: {a} ↔ {b}")
    return jsonify(snapshot())


@app.post("/api/v2v/message")
def api_v2v_message():
    a, b, msg = request.json.get("from"), request.json.get("to"), request.json.get("message", "").strip()
    if a not in state["vehicles"] or b not in state["vehicles"] or not msg:
        return jsonify({"error": "Invalid message"}), 400
    if not send_v2v(a, b, msg[:160], "INFO"):
        return jsonify({"error": "No V2V link between vehicles"}), 409
    return jsonify(snapshot())


@app.post("/api/control/message")
def api_control_message():
    b, msg = request.json.get("to"), request.json.get("message", "").strip()
    level = request.json.get("level", "WARN").upper()
    if b not in state["vehicles"] or not msg:
        return jsonify({"error": "Invalid control-room message"}), 400
    if level not in {"INFO", "WARN", "CRITICAL"}:
        level = "WARN"
    send_control(b, msg, level)
    return jsonify(snapshot())


@app.post("/api/hazard")
def api_hazard():
    data = request.json
    if not edge_data(data.get("a"), data.get("b")):
        return jsonify({"error": "Invalid road"}), 400
    key = road_key(data["a"], data["b"])
    state["hazards"].add(key)
    log_event("HAZARD", f"Road {key} blocked; routes recalculated")
    for vid in state["vehicles"]:
        send_control(vid, f"BAD ROAD: {key}. DO NOT ENTER. Road is blocked. Follow the recalculated safe route.", "CRITICAL")
    return jsonify(snapshot())


@app.post("/api/clear-hazards")
def api_clear_hazards():
    state["hazards"].clear()
    log_event("HAZARD", "All road hazards cleared")
    return jsonify(snapshot())


@app.post("/api/simulation")
def api_simulation():
    state["running"] = bool(request.json.get("running", True))
    log_event("SYSTEM", "Simulation " + ("started" if state["running"] else "paused"))
    return jsonify(snapshot())


@app.post("/api/reset")
def api_reset():
    state["fog"] = "clear"
    state["fog_sensor"] = 5.0
    state["fog_auto"] = True
    state["emergency"] = {"active": False, "source": None, "vehicle": None, "type": None, "type_label": None, "reason": "", "started_at": None, "cleared_at": None}
    state["driver_emergency_requests"].clear()
    state["incidents"].clear()
    state["incident_seq"] = 0
    state["hazards"].clear()
    state["vehicles"] = fresh_vehicles()
    state["v2v"] = {("V01", "V02"), ("V02", "V03"), ("V03", "V04")}
    state["messages"].clear()
    state["events"].clear()
    state["road_conflicts"] = {}
    state["auto_emergencies"] = {}
    state["running"] = True
    state["last_tick"] = time.time()
    log_event("SYSTEM", "Simulation reset")
    return jsonify(snapshot())


if __name__ == "__main__":
    app.run(debug=True)
