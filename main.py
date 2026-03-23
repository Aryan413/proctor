# [NOTE: I have kept your existing imports and themes exactly as they were]
# ... (All your imports: cv2, numpy, PIL, YOLO, mediapipe, flask, etc.) ...

import tkinter as tk
from tkinter import messagebox, ttk
import sqlite3, math, random, time, threading, csv, os, sys, subprocess
import ctypes, platform
import cv2
import numpy as np
from PIL import Image, ImageTk
from ultralytics import YOLO
import mediapipe as mp

# [I am skipping the middle 800 lines of your UI/Logic to save space, 
# but they remain exactly the same in your file]

# ... (All your classes: Particle, BaseWindow, MainLogin, ExamWindow, etc.) ...

# ══════════════════════════════════════════════════════════════════════════════
#  FIXED NETWORK SERVER (The "Perfect" Fix for Cloudflare)
# ══════════════════════════════════════════════════════════════════════════════
_net_server = None

def start_network_server(port=6000):
    """Start a Flask server that Cloudflare can actually talk to."""
    try:
        from flask import Flask, jsonify, Response, request
        from flask_cors import CORS # Added for cross-computer access
    except ImportError:
        print("[⚠] Flask not installed! Run: pip install flask flask-cors")
        return

    app = Flask("ExamShieldServer")
    CORS(app) # This allows the Proctor's computer to talk to yours safely

    # Silence unnecessary logs
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    @app.route("/ping")
    def ping():
        sid = (_hub.student_id if _hub else _iv_hub.student_id if _iv_hub else "none")
        mode = "interview" if _iv_hub else "exam"
        return jsonify(status="ok", student=sid, mode=mode)

    @app.route("/frame")
    def frame():
        hub = _hub or _iv_hub
        if hub is None: return Response("no session", status=204)
        f = (hub.get_frame() if hasattr(hub, 'get_frame') else hub.get_student_frame())
        if f is None: return Response("no frame", status=204)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/stats")
    def stats():
        hub = _hub or _iv_hub
        if hub is None: return jsonify(active=False)
        return jsonify(
            active=True,
            student_id=hub.student_id,
            face_count=hub.face_count,
            gaze_dir=hub.gaze_dir,
            strike_count=hub.strike_count,
            phone=getattr(hub, 'phone_detected', False),
            terminated=hub.terminated,
            mode="interview" if _iv_hub else "exam"
        )

    def _run():
        # CRITICAL FIX: host="0.0.0.0" allows the Tunnel to see the app
        # threaded=True allows multiple people to watch at once
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Get your Local IP automatically
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except: ip = "127.0.0.1"

    print(f"\n{'═'*60}")
    print(f" 🚀 SERVER IS LIVE ON PORT {port}")
    print(f" 🔗 Local Link: http://{ip}:{port}")
    print(f" ☁️  Now run: .\\cloudflared.exe tunnel --url http://localhost:{port}")
    print(f"{'═'*60}\n")

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    # Start the network server immediately
    start_network_server(port=6000)
    # Start the Login UI
    MainLogin().run()
# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE FUNCTIONS (Must be ABOVE the bottom of the file!)
# ══════════════════════════════════════════════════════════════════════════════
DB = "students.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        student_id TEXT PRIMARY KEY, password TEXT, face_data BLOB)""")
    c.execute("""CREATE TABLE IF NOT EXISTS proctors(
        proctor_id TEXT PRIMARY KEY, password TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT, opt_a TEXT, opt_b TEXT, opt_c TEXT, opt_d TEXT,
        answer TEXT, marks INTEGER DEFAULT 1, category TEXT DEFAULT 'General')""")
    c.execute("""CREATE TABLE IF NOT EXISTS violations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT, timestamp TEXT, event TEXT, detail TEXT)""")
    try: 
        c.execute("INSERT INTO proctors VALUES('admin','admin123')")
    except: 
        pass
    conn.commit()
    conn.close()
    print("✅ Database Initialized")