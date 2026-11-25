
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, request, redirect, render_template_string

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_KEY = os.environ.get("API_KEY", "")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "")
DB = os.environ.get("DB_PATH", "safety.db")
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------- DATABASE ----------------

def db():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS devices(
        device_id TEXT PRIMARY KEY,
        guard_name TEXT,
        chat_id TEXT
    );

    CREATE TABLE IF NOT EXISTS guardians(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        guard_name TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        UNIQUE(device_id, chat_id)
    );

    CREATE TABLE IF NOT EXISTS locations(
        device_id TEXT PRIMARY KEY,
        lat REAL,
        lng REAL,
        acc REAL,
        ts INTEGER
    );

    CREATE TABLE IF NOT EXISTS alerts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT,
        reason TEXT,
        lat REAL,
        lng REAL,
        source TEXT,
        area TEXT,
        ts INTEGER
    );
    """)

    old = c.execute(
        "SELECT device_id, guard_name, chat_id FROM devices"
    ).fetchall()

    for r in old:
        if r["chat_id"]:
            c.execute("""
            INSERT OR IGNORE INTO guardians
            (device_id, guard_name, chat_id)
            VALUES (?, ?, ?)
            """, (
                r["device_id"],
                r["guard_name"] or "Guardian",
                r["chat_id"]
            ))

    seed = os.environ.get("DEFAULT_CHAT_ID")

    if seed:
        c.execute("""
        INSERT OR IGNORE INTO devices
        VALUES ('DEV001', 'Security Guard 1', ?)
        """, (seed,))

        c.execute("""
        INSERT OR IGNORE INTO guardians
        (device_id, guard_name, chat_id)
        VALUES ('DEV001', 'Security Guard 1', ?)
        """, (seed,))

    c.commit()
    c.close()


init_db()


# ---------------- TELEGRAM ----------------

def tg(method, payload):
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload,
            timeout=15
        )
        print("Telegram:", r.status_code, r.text[:300])
        return r.ok
    except Exception as e:
        print("Telegram error:", e)
        return False


# ---------------- LOCATION ----------------

def reverse_geocode(lat, lng):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lng,
                "format": "json"
            },
            headers={"User-Agent": "IYAL-Hackathon/1.0"},
            timeout=8
        )
        return r.json().get("display_name", "Unknown area")
    except Exception as e:
        print("Geocoding error:", e)
        return "Location unavailable"


def get_location(device_id):
    c = db()
    row = c.execute(
        "SELECT * FROM locations WHERE device_id=?",
        (device_id,)
    ).fetchone()
    c.close()

    if row and int(time.time()) - row["ts"] < 1800:
        return row["lat"], row["lng"], row["acc"], "phone GPS"

    return None, None, None, "location unavailable"


# ---------------- DASHBOARD ----------------

@app.route("/")
def home():
    c = db()

    alerts = c.execute(
        "SELECT * FROM alerts ORDER BY id DESC LIMIT 50"
    ).fetchall()

    devices = c.execute(
        "SELECT * FROM devices ORDER BY device_id"
    ).fetchall()

    guardians = c.execute(
        "SELECT * FROM guardians ORDER BY device_id"
    ).fetchall()

    c.close()

    alert_data = [dict(r) for r in alerts]

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
    <title>IYAL | Safety Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    <style>
    body{font-family:Arial;margin:0;background:#f5f6fa;color:#222}
    header{background:#171b36;color:white;padding:22px}
    header h1{margin:0;color:#ff7ca8}
    main{padding:18px;max-width:1100px;margin:auto}
    .card{background:white;padding:18px;margin:15px 0;
    border-radius:12px;box-shadow:0 2px 8px #ddd}
    #map{height:350px;border-radius:10px}
    table{width:100%;border-collapse:collapse}
    th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}
    input{padding:10px;margin:5px;max-width:100%;box-sizing:border-box}
    button{padding:10px 18px;background:#e84d83;color:white;
    border:0;border-radius:6px;cursor:pointer}
    .status{color:#15966c;font-weight:bold}
    .scroll{overflow-x:auto}
    </style>
    </head>
    <body>
    <header>
    <h1>IYAL</h1>
    <p>Intelligent Your Alert Link | Personal Safety System</p>
    <span class="status">● System Dashboard</span>
    </header>

    <main>
    <div class="card">
    <h2>Emergency Location Map</h2>
    <div id="map"></div>
    </div>

    <div class="card">
    <h2>Recent Emergency Alerts</h2>
    <div class="scroll">
    <table>
    <tr><th>Time</th><th>Device</th><th>Trigger</th>
    <th>Area</th><th>Source</th></tr>
    {% for a in alerts %}
    <tr>
    <td>{{ a.ts|datetime }}</td>
    <td>{{ a.device_id }}</td>
    <td>{{ a.reason }}</td>
    <td>{{ a.area }}</td>
    <td>{{ a.source }}</td>
    </tr>
    {% else %}
    <tr><td colspan="5">No alerts yet</td></tr>
    {% endfor %}
    </table>
    </div>
    </div>

    <div class="card">
    <h2>Registered Devices</h2>
    <div class="scroll">
    <table>
    <tr><th>Device</th><th>Guard</th><th>Telegram Chat ID</th></tr>
    {% for g in guardians %}
    <tr><td>{{g.device_id}}</td>
    <td>{{g.guard_name}}</td><td>{{g.chat_id}}</td></tr>
    {% endfor %}
    </table>
    </div>
    <h3>Device Companion Links</h3>
    {% for d in devices %}
    <p>{{d.device_id}} :
    <a href="/phone/{{d.device_id}}">Open GPS page</a></p>
    {% endfor %}
    </div>

    <div class="card">
    <h2>Register a Device / Guardian</h2>
    <form action="/admin/register" method="POST">
    <input name="device_id" placeholder="Device ID (DEV002)" required>
    <input name="guard_name" placeholder="Guard name" required>
    <input name="chat_id" placeholder="Telegram Chat ID" required>
    <input name="pin" placeholder="Admin PIN" required>
    <button type="submit">Register</button>
    </form>
    </div>

    <p style="text-align:center">IYAL © 2026 | Emergency Safety Network</p>
    </main>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
    const alerts = {{ alert_data|tojson }};
    const map = L.map('map').setView([11.0168,76.9558],12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {attribution:'© OpenStreetMap'}).addTo(map);

    const points = [];
    alerts.forEach(a=>{
      if(a.lat !== null && a.lng !== null){
        const p=[a.lat,a.lng];
        points.push(p);
        L.marker(p).addTo(map)
        .bindPopup('<b>IYAL Emergency Alert</b><br>'+a.area);
      }
    });
    if(points.length){
      map.fitBounds(points,{padding:[30,30],maxZoom:16});
    }
    </script>
    </body>
    </html>
    """,
    alerts=alerts,
    devices=devices,
    guardians=guardians,
    alert_data=alert_data)


@app.template_filter("datetime")
def format_time(ts):
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %I:%M:%S %p")


# ---------------- PHONE GPS PAGE ----------------

@app.route("/phone/<device_id>")
def phone(device_id):
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
    <title>IYAL GPS Sharing</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body style="font-family:Arial;text-align:center;padding:30px">
    <h1 style="color:#e84d83">IYAL</h1>
    <h2>Live Location Sharing</h2>
    <p id="status">Requesting GPS permission...</p>
    <p>Keep this page open for location updates.</p>

    <script>
    const device = {{ device_id|tojson }};
    const statusText = document.getElementById("status");

    if(!navigator.geolocation){
      statusText.innerText="GPS is not supported by this browser.";
    }else{
      navigator.geolocation.watchPosition(async pos=>{
        const data={
          device_id:device,
          lat:pos.coords.latitude,
          lng:pos.coords.longitude,
          accuracy:pos.coords.accuracy
        };

        try{
          const r=await fetch("/api/location",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify(data)
          });

          if(r.ok){
            statusText.innerText=
            "Sharing live location. Accuracy: about "+
            Math.round(pos.coords.accuracy)+" metres.";
          }else{
            statusText.innerText="Could not update location.";
          }
        }catch(e){
          statusText.innerText="Connection error. Retrying...";
        }
      },err=>{
        statusText.innerText="Location permission/error: "+err.message;
      },{enableHighAccuracy:true,maximumAge:5000,timeout:20000});
    }
    </script>
    </body>
    </html>
    """, device_id=device_id)


# ---------------- RECEIVE PHONE GPS ----------------

@app.route("/api/location", methods=["POST"])
def receive_location():
    data = request.get_json(silent=True) or {}

    device_id = str(data.get("device_id", "")).strip()

    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
        accuracy = float(data.get("accuracy", data.get("acc", 0)))

        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Invalid coordinates")

    except (TypeError, ValueError):
        return jsonify({"error": "Invalid location coordinates"}), 400

    if not device_id:
        return jsonify({"error": "Device ID required"}), 400

    c = db()
    c.execute("""
    INSERT OR REPLACE INTO locations
    (device_id,lat,lng,acc,ts) VALUES(?,?,?,?,?)
    """, (device_id, lat, lng, accuracy, int(time.time())))
    c.commit()
    c.close()

    return jsonify({"success": True, "accuracy": accuracy})


# ---------------- RECEIVE ESP32 ALERT ----------------

@app.route("/api/alert", methods=["POST"])
def receive_alert():
    data = request.get_json(silent=True) or {}

    supplied_key = (
        request.headers.get("X-API-Key")
        or data.get("api_key")
        or data.get("key")
    )

    if not API_KEY or supplied_key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    device_id = str(data.get("device_id", "DEV001")).strip()
    reason = str(
        data.get("reason")
        or data.get("trigger")
        or data.get("event")
        or "Panic button"
    )

    lat, lng, accuracy, source = get_location(device_id)

    # Accept coordinates supplied directly by the ESP32 too.
    try:
        if data.get("lat") is not None and data.get("lng") is not None:
            lat = float(data["lat"])
            lng = float(data["lng"])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError()
            source = "device GPS"
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid coordinates"}), 400

    area = "Location unavailable"

    if lat is not None and lng is not None:
        area = reverse_geocode(lat, lng)

    c = db()

    guards = c.execute("""
    SELECT chat_id,guard_name FROM guardians WHERE device_id=?
    """, (device_id,)).fetchall()

    # Backward compatibility with the original devices table.
    if not guards:
        old = c.execute("""
        SELECT chat_id,guard_name FROM devices WHERE device_id=?
        """, (device_id,)).fetchone()
        if old and old["chat_id"]:
            guards = [old]

    if not guards:
        c.close()
        return jsonify({"error": "Device not registered"}), 404

    ts = int(time.time())

    c.execute("""
    INSERT INTO alerts(device_id,reason,lat,lng,source,area,ts)
    VALUES(?,?,?,?,?,?,?)
    """, (device_id, reason, lat, lng, source, area, ts))

    c.commit()
    c.close()

    message = (
        "🚨 IYAL EMERGENCY ALERT 🚨\n\n"
        f"Device: {device_id}\n"
        f"Trigger: {reason}\n"
        f"Area: {area}\n"
        f"Location source: {source}\n"
    )

    if accuracy is not None:
        message += f"GPS accuracy: approximately {round(accuracy)} metres\n"

    if lat is not None and lng is not None:
        message += f"\nMap: https://www.google.com/maps?q={lat},{lng}"

    sent = 0

    for guard in guards:
        ok = tg("sendMessage", {
            "chat_id": guard["chat_id"],
            "text": message
        })

        if ok:
            sent += 1

        if lat is not None and lng is not None:
            tg("sendLocation", {
                "chat_id": guard["chat_id"],
                "latitude": lat,
                "longitude": lng
            })

    return jsonify({
        "success": True,
        "device_id": device_id,
        "telegram_sent": sent,
        "location_source": source,
        "area": area
    }), 200


# ---------------- REGISTER GUARDIAN ----------------

@app.route("/admin/register", methods=["POST"])
def register():
    if not ADMIN_PIN or request.form.get("pin") != ADMIN_PIN:
        return "Incorrect admin PIN. Please go back and try again.", 403

    device_id = request.form.get("device_id", "").strip()
    guard_name = request.form.get("guard_name", "").strip()
    chat_id = request.form.get("chat_id", "").strip()

    if not device_id or not guard_name or not chat_id:
        return "All fields are required.", 400

    c = db()

    c.execute("""
    INSERT OR IGNORE INTO devices(device_id,guard_name,chat_id)
    VALUES(?,?,?)
    """, (device_id, guard_name, chat_id))

    c.execute("""
    INSERT OR IGNORE INTO guardians(device_id,guard_name,chat_id)
    VALUES(?,?,?)
    """, (device_id, guard_name, chat_id))

    c.commit()
    c.close()

    return redirect("/")


# ---------------- HEALTH CHECK ----------------

@app.route("/health")
def health():
    return jsonify({"status": "online", "project": "IYAL"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
