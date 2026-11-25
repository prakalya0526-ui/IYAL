"""SafeAlert server: receives alerts from the ESP32, finds the registered guard,
attaches the best available location and notifies the guard on Telegram."""
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, redirect, render_template_string, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")        # set on the server, never in GitHub
API_KEY = os.environ.get("API_KEY", "demo-key")    # shared secret with the ESP32
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")    # needed to register guards
DB = os.environ.get("DB_PATH", "safety.db")
IST = timezone(timedelta(hours=5, minutes=30))


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS devices(
            device_id TEXT PRIMARY KEY, guard_name TEXT, chat_id TEXT);
        CREATE TABLE IF NOT EXISTS locations(
            device_id TEXT PRIMARY KEY, lat REAL, lng REAL, acc REAL, ts INTEGER);
        CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, reason TEXT,
            lat REAL, lng REAL, source TEXT, area TEXT, ts INTEGER);
        """
    )
    seed = os.environ.get("DEFAULT_CHAT_ID")  # auto-registers DEV001 on every start
    if seed:
        c.execute("INSERT OR IGNORE INTO devices VALUES ('DEV001','Security Guard 1',?)", (seed,))
    c.commit()
    c.close()


init_db()


def tg(method, payload):
    if not BOT_TOKEN:
        print("BOT_TOKEN not set; would send:", method, payload)
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=10)
        print("telegram", method, r.status_code)
    except Exception as e:
        print("telegram error:", e)


def reverse_geocode(lat, lng):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "json"},
            headers={"User-Agent": "safealert-hackathon"},
            timeout=5,
        ).json()
        return r.get("display_name", "Unknown area")
    except Exception:
        return "Unknown area"


def ip_location(ip):
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,lat,lon", timeout=5).json()
        if r.get("status") == "success":
            return r["lat"], r["lon"]
    except Exception:
        pass
    return None, None


@app.post("/api/location")
def save_location():
    """Called by the phone companion page every few seconds with real GPS."""
    d = request.get_json(force=True)
    c = db()
    c.execute(
        "INSERT OR REPLACE INTO locations VALUES (?,?,?,?,?)",
        (d["device_id"], d["lat"], d["lng"], d.get("acc", 0), int(time.time())),
    )
    c.commit()
    c.close()
    return jsonify(ok=True)


@app.post("/api/alert")
def alert():
    """Called by the ESP32 when the panic button is confirmed."""
    d = request.get_json(force=True)
    if d.get("key") != API_KEY:
        return jsonify(error="unauthorized"), 401
    dev = d.get("device_id", "")
    c = db()
    guard = c.execute("SELECT * FROM devices WHERE device_id=?", (dev,)).fetchone()
    if not guard:
        c.close()
        return jsonify(error="device not registered"), 404

    lat = lng = None
    source = "unavailable"
    loc = c.execute("SELECT * FROM locations WHERE device_id=?", (dev,)).fetchone()
    if loc and time.time() - loc["ts"] < 600:  # phone GPS fresher than 10 minutes
        lat, lng = loc["lat"], loc["lng"]
        source = f"phone GPS (about {int(loc['acc'] or 0)} m accuracy)"
    else:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        lat, lng = ip_location(ip)
        if lat is not None:
            source = "approximate (internet connection, city level)"

    area = reverse_geocode(lat, lng) if lat is not None else "Unknown"
    reason = d.get("reason", "panic button")
    c.execute(
        "INSERT INTO alerts(device_id,reason,lat,lng,source,area,ts) VALUES (?,?,?,?,?,?,?)",
        (dev, reason, lat, lng, source, area, int(time.time())),
    )
    c.commit()
    c.close()

    now = datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p")
    text = f"🚨 EMERGENCY ALERT 🚨\nDevice: {dev}\nTrigger: {reason}\nTime: {now}\n"
    if lat is not None:
        text += (f"Area: {area}\nLat/Lng: {lat:.5f}, {lng:.5f}\nLocation source: {source}\n"
                 f"Map: https://maps.google.com/?q={lat},{lng}")
    else:
        text += "Location unavailable."
    tg("sendMessage", {"chat_id": guard["chat_id"], "text": text})
    if lat is not None:
        tg("sendLocation", {"chat_id": guard["chat_id"], "latitude": lat, "longitude": lng})
    return jsonify(ok=True, source=source)


@app.post("/register")
def register():
    f = request.form
    if f.get("pin") != ADMIN_PIN:
        return "Wrong admin PIN", 403
    c = db()
    c.execute(
        "INSERT OR REPLACE INTO devices VALUES (?,?,?)",
        (f["device_id"].strip(), f["guard_name"].strip(), f["chat_id"].strip()),
    )
    c.commit()
    c.close()
    return redirect("/")


@app.get("/phone/<dev>")
def phone(dev):
    return render_template_string(PHONE, dev=dev)


@app.get("/")
def home():
    c = db()
    alerts = [dict(r) for r in c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 20")]
    devices = [dict(r) for r in c.execute("SELECT * FROM devices")]
    c.close()
    for a in alerts:
        a["t"] = datetime.fromtimestamp(a["ts"], IST).strftime("%d %b %H:%M:%S")
    return render_template_string(PAGE, alerts=alerts, devices=devices)


PHONE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>SafeAlert Companion</title>
<body style="font-family:sans-serif;padding:20px;text-align:center">
<h2>🛡️ SafeAlert Companion</h2>
<p>Device: <b>{{dev}}</b></p>
<p id=s>Waiting for GPS permission...</p>
<p style="color:#666;font-size:13px">Keep this page open and the screen on.
Your precise location is shared only with your registered guard when you press the alert button.</p>
<script>
navigator.geolocation.watchPosition(p=>{
  fetch("/api/location",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({device_id:"{{dev}}",lat:p.coords.latitude,lng:p.coords.longitude,acc:p.coords.accuracy})});
  document.getElementById("s").textContent="Sharing live location (accuracy ~"+Math.round(p.coords.accuracy)+" m)";
},e=>{document.getElementById("s").textContent="GPS error: "+e.message},{enableHighAccuracy:true});
</script></body>"""

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>SafeAlert Dashboard</title>
<link rel=stylesheet href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{font-family:sans-serif;max-width:960px;margin:auto;padding:12px}
#m{height:340px;border-radius:8px}table{width:100%;border-collapse:collapse}
td,th{border-bottom:1px solid #ddd;padding:6px;font-size:14px;text-align:left}
input{padding:6px;margin:2px}</style>
<h1>🚨 SafeAlert Dashboard</h1>
<div id=m></div>
<h3>Recent alerts</h3>
<table><tr><th>Time</th><th>Device</th><th>Trigger</th><th>Area</th><th>Source</th></tr>
{% for a in alerts %}<tr><td>{{a.t}}</td><td>{{a.device_id}}</td><td>{{a.reason}}</td>
<td>{{a.area}}</td><td>{{a.source}}</td></tr>
{% else %}<tr><td colspan=5>No alerts yet.</td></tr>{% endfor %}</table>
<h3>Registered devices and guards</h3>
<table><tr><th>Device</th><th>Guard</th><th>Companion link</th></tr>
{% for d in devices %}<tr><td>{{d.device_id}}</td><td>{{d.guard_name}}</td>
<td><a href="/phone/{{d.device_id}}">/phone/{{d.device_id}}</a></td></tr>{% endfor %}</table>
<h3>Register a device (admin)</h3>
<form method=post action="/register">
<input name=device_id placeholder="Device ID e.g. DEV002" required>
<input name=guard_name placeholder="Guard name" required>
<input name=chat_id placeholder="Guard Telegram chat ID" required>
<input name=pin type=password placeholder="Admin PIN" required>
<button>Save</button></form>
<script>
const pts={{alerts|tojson}}.filter(a=>a.lat!==null);
const map=L.map('m').setView(pts.length?[pts[0].lat,pts[0].lng]:[20.59,78.96],pts.length?15:4);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map);
pts.forEach(a=>L.marker([a.lat,a.lng]).addTo(map).bindPopup(a.device_id+" · "+a.t+"<br>"+a.source));
</script>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
