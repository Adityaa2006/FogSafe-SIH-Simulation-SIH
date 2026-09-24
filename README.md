
# FogSafe SIH Simulation v8 – Smart Emergency Workflow

🚀 Live Demo

Experience the FogSafe – SIH Simulation live:

👉 "Open Live Demo" ((https://fogsafe-sih-simulation-sih.onrender.com/))

«The application is deployed on Render. The free hosting service may put the application to sleep after a period of inactivity, so the first request may take a short time to load.»

🔗 Project Repository

👉 "GitHub Repository" (https://github.com/Adityaa2006/FogSafe-SIH-Simulation-SIH)
## Run
```powershell
cd fogsafe
python -m pip install flask --break-system-packages   # if Flask isn't installed
python app.py
```

Requires only `Flask` (standard library `heapq`, `math`, `random`, `time`,
`collections` are used otherwise). Tested end-to-end: all three pages, all
static assets, and the fog-sensor auto/manual/reset flows respond correctly.

Open:
- Control Room: http://127.0.0.1:5000/
- Driver Dashboard: http://127.0.0.1:5000/driver
- Emergency Operations: http://127.0.0.1:5000/emergency

## Automatic fog detection
Instead of manually choosing the environment, the Control Room now reads a
simulated **fog sensor score (0–100)** that drifts on its own each tick and is
mapped to an environment band automatically:

| Score range | Environment |
|---|---|
| 0 – 10  | CLEAR |
| 10 – 30 | MODERATE |
| 30 – 60 | DENSE |
| 60 – 100 | CRITICAL |

- The Control Room toolbar shows the live sensor score and current mode
  (`AUTO` / `MANUAL`).
- Clicking **AUTO: ON/OFF** toggles automatic detection.
- The CLEAR / MODERATE / DENSE / CRITICAL buttons still work as a manual
  override — using one switches the sensor to manual mode and fixes the
  environment; toggle AUTO back on to hand control back to the sensor.
- Resetting the simulation (`Reset` button / `/api/reset`) returns the sensor
  to a low clear-weather score and re-enables automatic mode.
- New API routes: `POST /api/fog/auto {"auto": true|false}` to switch modes;
  `GET /api/state` now also returns `fog_sensor` and `fog_auto`.

## Emergency workflow
- Driver emergency opens a 3-second safety window.
- Driver can submit a manual emergency with a reason.
- If the driver cannot complete the manual request within 3 seconds, FogSafe automatically sends a **Driver Auto-Fallback Emergency** to the Control Room.
- Control Room receives the request and can use **ALL OK — CLEAR ALL** to clear every active AI/control/driver emergency.
- ALL OK restores affected connected vehicles to normal travel and sends the driver a localized ALL OK message.
- AI-detected emergencies remain separate from driver-originated emergencies.
