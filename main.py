"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                         ExamShield  v2.0                                    ║
║                  AI-Powered Secure Assessment Platform                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Run:   python main.py                                                       ║
║  Login: admin / admin123  (proctor)                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  FEATURES                                                                    ║
║  ① Face verification at login (face_recognition or MediaPipe fallback)       ║
║  ② Tab-switch detection → instant strike                                     ║
║  ③ Blocked apps list (ChatGPT, browser, notepad, etc.) → strike on detect   ║
║  ④ Keystroke blocking (Ctrl+C/V/A/Tab/Alt+Tab/Win key)                       ║
║  ⑤ Question randomisation (order shuffled per session)                       ║
║  ⑥ Two modes on login: EXAM  and  INTERVIEW                                 ║
║  ⑦ EXAM mode  → student camera hidden; proctor sees live feed + violations  ║
║  ⑧ INTERVIEW mode → both cameras open simultaneously (like Google Meet)     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Folder layout expected:
  main.py
  proctor.py          (kept for reference, not called directly)
  face_auth.py
  students.db         (auto-created)
  gaze_tracking/
      __init__.py
      gaze_tracking.py   (MediaPipe head-yaw version)
      eye.py  calibration.py  pupil.py
"""

# ─────────────────────────────────────────────────────────────────────────────
#  STDLIB
# ─────────────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import messagebox, ttk
import sqlite3, math, random, time, threading, csv, os, sys, subprocess
import ctypes, platform

# ─────────────────────────────────────────────────────────────────────────────
#  HEAVY LIBS  (imported at module level; login screen still feels instant
#               because the Tk mainloop starts before YOLO weights load)
# ─────────────────────────────────────────────────────────────────────────────
import cv2
import numpy as np
from PIL import Image, ImageTk
from ultralytics import YOLO
import mediapipe as mp

# ─────────────────────────────────────────────────────────────────────────────
#  WINDOWS-ONLY keyboard hook (graceful fallback on other OS)
# ─────────────────────────────────────────────────────────────────────────────
_KEYBOARD_HOOK_AVAILABLE = False
try:
    import keyboard  # pip install keyboard
    _KEYBOARD_HOOK_AVAILABLE = True
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
#  PROCESS MONITOR  (psutil — optional but strongly recommended)
# ─────────────────────────────────────────────────────────────────────────────
_PSUTIL_AVAILABLE = False
try:
    import psutil  # pip install psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════════
#  THEMES
# ══════════════════════════════════════════════════════════════════════════════
DARK = {
    "bg":"#0d1117","canvas_bg":"#0d1117","card_bg":"#161b22","card_border":"#30363d",
    "title_fg":"#58d6d6","subtitle_fg":"#8b949e","label_fg":"#c9d1d9",
    "entry_bg":"#21262d","entry_fg":"#f0f6fc","entry_border":"#30363d","entry_focus":"#58d6d6",
    "btn_primary_bg":"#0be881","btn_primary_fg":"#0d1117",
    "btn_secondary_bg":"#575fcf","btn_secondary_fg":"#ffffff",
    "btn_toggle_bg":"#21262d","btn_toggle_fg":"#c9d1d9",
    "pill_active_bg":"#58d6d6","pill_active_fg":"#0d1117",
    "pill_inactive_bg":"#21262d","pill_inactive_fg":"#8b949e",
    "particle_colors":["#58d6d6","#0be881","#575fcf","#ff6b9d","#ffd93d"],
    "mode_icon":"☀️","mode_text":"Light Mode",
    "proctor_accent":"#ff6b9d","student_accent":"#0be881",
    "interview_accent":"#ffd93d",
}
LIGHT = {
    "bg":"#f0f4f8","canvas_bg":"#f0f4f8","card_bg":"#ffffff","card_border":"#d0d7de",
    "title_fg":"#0969da","subtitle_fg":"#57606a","label_fg":"#24292f",
    "entry_bg":"#f6f8fa","entry_fg":"#24292f","entry_border":"#d0d7de","entry_focus":"#0969da",
    "btn_primary_bg":"#1a7f37","btn_primary_fg":"#ffffff",
    "btn_secondary_bg":"#8250df","btn_secondary_fg":"#ffffff",
    "btn_toggle_bg":"#e7edf3","btn_toggle_fg":"#24292f",
    "pill_active_bg":"#0969da","pill_active_fg":"#ffffff",
    "pill_inactive_bg":"#eaeef2","pill_inactive_fg":"#57606a",
    "particle_colors":["#0969da","#1a7f37","#8250df","#cf222e","#9a6700"],
    "mode_icon":"🌙","mode_text":"Dark Mode",
    "proctor_accent":"#cf222e","student_accent":"#1a7f37",
    "interview_accent":"#9a6700",
}

# ══════════════════════════════════════════════════════════════════════════════
#  BLOCKED APPS  (process name substrings, lowercase)
# ══════════════════════════════════════════════════════════════════════════════
# Exact process names (lowercase) with visible windows to block
# ── Apps flagged ONLY when student actively switches to them (foreground) ─────
BLOCKED_IF_FOREGROUND = {
    "chrome.exe","firefox.exe","msedge.exe","opera.exe","brave.exe",
    "vivaldi.exe","arc.exe","notepad.exe","notepad++.exe","wordpad.exe",
    "winword.exe","soffice.exe","sublime_text.exe",
    "zoom.exe","discord.exe","slack.exe","skype.exe","telegram.exe",
    "whatsapp.exe","signal.exe","teamviewer.exe","anydesk.exe","rustdesk.exe",
    "obs64.exe","obs32.exe","camtasia.exe","bandicam.exe",
}

# ── Window title keywords — only flagged when that window is in FOREGROUND ────
BLOCKED_WINDOW_TITLES = [
    "chatgpt","claude.ai","gemini","copilot","chegg","quizlet",
    "google translate","grammarly","wolfram","photomath",
]

# ── NEVER flagged — crash handlers, updaters, drivers, system services ────────
# Background processes that run legitimately with no user interaction
SYSTEM_WHITELIST = {
    # This app
    "python.exe","python3.exe","pythonw.exe",
    # Windows core
    "explorer.exe","conhost.exe","svchost.exe","taskhostw.exe",
    "runtimebroker.exe","werfault.exe","werfaultsecure.exe",
    "dllhost.exe","sihost.exe","ctfmon.exe","fontdrvhost.exe",
    "dwm.exe","winlogon.exe","csrss.exe","smss.exe","lsass.exe",
    "services.exe","spoolsv.exe","searchindexer.exe","searchhost.exe",
    "systemsettings.exe","startmenuexperiencehost.exe",
    "shellexperiencehost.exe","applicationframehost.exe","textinputhost.exe",
    "userinit.exe","unsecapp.exe","taskmgr.exe","msiexec.exe",
    # Crash handlers / reporters — NEVER cheating, just background cleanup
    "bravecrashhandler.exe","bravecrashhandler64.exe",
    "crashpad_handler.exe","crashreporter.exe",
    "chromiumcrashhandler.exe","msedgecrashhndlr.exe",
    "firefoxcrashhandler.exe","googlecrashhandler.exe","googlecrashhandler64.exe",
    "discordcrashhandler.exe","werfault.exe",
    # Auto-updaters (background, no user action)
    "googleupdate.exe","googleupdatebroker.exe",
    "braveupdater.exe","msedgeupdate.exe","firefoxdefaultbrowser.exe",
    # Browser WebView helpers (background rendering, not browsing)
    "msedgewebview2.exe",
    # Anti-virus
    "msmpeng.exe","nissrv.exe","securityhealthservice.exe",
    "mbam.exe","mbamservice.exe","avgnt.exe","avguard.exe",
    # GPU / display drivers
    "nvdisplay.container.exe","nvcontainer.exe","audiodg.exe",
    "amdrsserv.exe","radeoninstaller.exe",
    # Notification / taskbar
    "notificationplatformhelper.exe","widgets.exe","widgetservice.exe",
    "phonelinkservice.exe","yourphone.exe",
    # Windows telemetry / update
    "wuauclt.exe","musnotifyicon.exe","compattelrunner.exe","diaghost.exe",
    # VS Code background (language server, not the editor window)
    "code.exe","code - insiders.exe",
    # Common game launchers that idle silently
    "steamservice.exe","epicgameslauncher.exe",
}

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE
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
    try: c.execute("INSERT INTO proctors VALUES('admin','admin123')")
    except: pass
    if c.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0:
        seed = [
            ("What does CPU stand for?","Central Processing Unit","Central Program Unit",
             "Computer Personal Unit","Control Processing Unit","A",1,"CS"),
            ("Which language is used for web pages?","Python","Java","HTML","C++","C",1,"Web"),
            ("What is 2^10?","512","1024","2048","256","B",1,"Math"),
            ("Who invented the World Wide Web?","Bill Gates","Tim Berners-Lee",
             "Steve Jobs","Linus Torvalds","B",1,"General"),
            ("What does RAM stand for?","Random Access Memory","Read Access Module",
             "Remote Access Memory","Rapid Access Module","A",1,"CS"),
            ("Which data structure uses LIFO?","Queue","Stack","Tree","Graph","B",1,"CS"),
            ("Binary of decimal 5?","101","110","100","111","A",1,"Math"),
            ("Protocol used to send emails?","HTTP","FTP","SMTP","SSH","C",1,"Networks"),
        ]
        c.executemany(
            "INSERT INTO questions(question,opt_a,opt_b,opt_c,opt_d,answer,marks,category)"
            " VALUES(?,?,?,?,?,?,?,?)", seed)
    conn.commit(); conn.close()

def db_get_user(uid, pwd, role="student"):
    conn = sqlite3.connect(DB)
    col = "student_id" if role=="student" else "proctor_id"
    tbl = "users"      if role=="student" else "proctors"
    row = conn.execute(f"SELECT * FROM {tbl} WHERE {col}=? AND password=?",(uid,pwd)).fetchone()
    conn.close(); return row

def db_register(uid, pwd):
    conn = sqlite3.connect(DB)
    try:
        conn.execute("INSERT INTO users(student_id,password) VALUES(?,?)",(uid,pwd))
        conn.commit(); conn.close(); return True
    except sqlite3.IntegrityError:
        conn.close(); return False

def db_get_questions():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    conn.close(); return rows

def db_add_question(q,a,b,c,d,ans,marks=1,cat="General"):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO questions(question,opt_a,opt_b,opt_c,opt_d,answer,marks,category)"
                 " VALUES(?,?,?,?,?,?,?,?)",(q,a,b,c,d,ans,marks,cat))
    conn.commit(); conn.close()

def db_update_question(qid,q,a,b,c,d,ans,marks,cat):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE questions SET question=?,opt_a=?,opt_b=?,opt_c=?,opt_d=?,"
                 "answer=?,marks=?,category=? WHERE id=?",(q,a,b,c,d,ans,marks,cat,qid))
    conn.commit(); conn.close()

def db_delete_question(qid):
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM questions WHERE id=?",(qid,)); conn.commit(); conn.close()

def db_log_violation(student_id, event, detail=""):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO violations(student_id,timestamp,event,detail) VALUES(?,?,?,?)",
                 (student_id,time.strftime("%H:%M:%S"),event,detail))
    conn.commit(); conn.close()

# ══════════════════════════════════════════════════════════════════════════════
#  SECURITY MONITOR  (tab-switch, app-blocking, keystroke-blocking)
# ══════════════════════════════════════════════════════════════════════════════
class SecurityMonitor:
    """
    Runs in a background thread alongside the exam.
    Detects:
      • Tab switching / window focus loss
      • Blocked apps running
      • Blocked keystrokes (Ctrl+C/V/A, Alt+Tab, Win key)
    Calls on_violation(event, detail) on the main thread via root.after.
    """
    POLL_MS = 1000   # check every second

    def __init__(self, root, student_id, on_violation):
        self.root          = root
        self.student_id    = student_id
        self.on_violation  = on_violation
        self.running       = True
        self._warned_apps  = set()
        self._thread       = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._setup_key_blocks()
        self._thread.start()

    def stop(self):
        self.running = False
        self._remove_key_blocks()

    # ── key blocking ─────────────────────────────────────────────────────
    def _setup_key_blocks(self):
        if not _KEYBOARD_HOOK_AVAILABLE: return
        blocked = [
            ("ctrl+c",     "Copy blocked"),
            ("ctrl+v",     "Paste blocked"),
            ("ctrl+a",     "Select-all blocked"),
            ("ctrl+x",     "Cut blocked"),
            ("ctrl+z",     "Undo blocked"),
            ("alt+tab",    "Alt+Tab blocked"),
            ("windows",    "Win key blocked"),
            ("ctrl+tab",   "Ctrl+Tab blocked"),
            ("ctrl+w",     "Close-tab blocked"),
            ("ctrl+t",     "New-tab blocked"),
            ("ctrl+n",     "New-window blocked"),
            ("ctrl+alt+delete", "CAD blocked"),
            ("printscreen","Screenshot blocked"),
        ]
        self._hooks = []
        for keys, msg in blocked:
            try:
                h = keyboard.add_hotkey(keys,
                    lambda m=msg: self.root.after(0, lambda: self.on_violation("KEYSTROKE", m)),
                    suppress=True)
                self._hooks.append(h)
            except Exception:
                pass

    def _remove_key_blocks(self):
        if not _KEYBOARD_HOOK_AVAILABLE: return
        try: keyboard.unhook_all_hotkeys()
        except: pass

    # ── background thread ────────────────────────────────────────────────
    # Grace period: foreground app must stay blocked for this many seconds
    # before a strike fires. Prevents notification popups from striking.
    APP_GRACE_SECS  = 5.0   # app must be in foreground 5s before strike
    TAB_GRACE_SECS  = 3.0   # tab switch must persist 3s before strike
    TAB_COOLDOWN    = 8.0   # minimum seconds between tab-switch strikes

    def _safe_call(self, fn):
        """Only schedule callback if root window still exists."""
        try:
            if self.root.winfo_exists() and self.running:
                self.root.after(0, fn)
        except Exception:
            pass

    def _run(self):
        # Give exam window time to fully open before we start watching
        time.sleep(4)

        # Grace-period timers keyed by app/event name
        _app_first_seen  = {}   # pname/kw → time first seen in foreground
        _tab_first_seen  = None # time tab-switch first detected
        _last_tab_strike = 0.0

        while self.running:
            time.sleep(self.POLL_MS / 1000)
            if not self.running:
                break

            now = time.time()

            # ── Win32 foreground window check ─────────────────────────
            fg_title     = ""
            fg_proc_name = ""
            if platform.system() == "Windows":
                try:
                    import win32gui, win32process
                    fg_hwnd  = win32gui.GetForegroundWindow()
                    fg_title = win32gui.GetWindowText(fg_hwnd).lower()
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(fg_hwnd)
                        proc = psutil.Process(pid) if _PSUTIL_AVAILABLE else None
                        fg_proc_name = (proc.name().lower() if proc else "")
                    except Exception:
                        fg_proc_name = ""
                except ImportError:
                    pass

            exam_has_focus = "examshield" in fg_title or fg_title == ""

            # ── TAB SWITCH: only strike after grace period ────────────
            if not exam_has_focus and fg_title and len(fg_title) > 2:
                if _tab_first_seen is None:
                    _tab_first_seen = now   # start grace timer
                elif now - _tab_first_seen >= self.TAB_GRACE_SECS:
                    if now - _last_tab_strike >= self.TAB_COOLDOWN:
                        _last_tab_strike = now
                        t = fg_title
                        self._safe_call(lambda t=t: self.on_violation(
                            "TAB_SWITCH", f"Switched to: {t[:40]}"))
            else:
                _tab_first_seen = None   # reset — student came back

            # ── FOREGROUND WINDOW TITLE check (AI/cheat sites) ────────
            # Only checks the active window — a background browser tab never triggers this
            if fg_title and not exam_has_focus:
                for kw in BLOCKED_WINDOW_TITLES:
                    if kw in fg_title:
                        key = f"title:{kw}"
                        if key not in _app_first_seen:
                            _app_first_seen[key] = now
                        elif (now - _app_first_seen[key] >= self.APP_GRACE_SECS
                              and key not in self._warned_apps):
                            self._warned_apps.add(key)
                            self._safe_call(lambda k=kw: self.on_violation(
                                "BLOCKED_APP", f"Cheating site open: {k}"))

            # ── FOREGROUND PROCESS check ──────────────────────────────
            # Only fires if the blocked app IS the foreground window AND
            # student has been on it for APP_GRACE_SECS.
            # Background crash handlers / updaters are never the foreground window.
            if fg_proc_name and fg_proc_name not in SYSTEM_WHITELIST:
                if fg_proc_name in BLOCKED_IF_FOREGROUND:
                    key = f"proc:{fg_proc_name}"
                    if key not in _app_first_seen:
                        _app_first_seen[key] = now   # start grace timer
                        # Log a warning immediately (not a strike yet)
                        self._safe_call(lambda p=fg_proc_name: self.on_violation(
                            "APP_WARNING", f"{p} in foreground — monitoring…"))
                    elif (now - _app_first_seen[key] >= self.APP_GRACE_SECS
                          and key not in self._warned_apps):
                        self._warned_apps.add(key)
                        self._safe_call(lambda p=fg_proc_name: self.on_violation(
                            "BLOCKED_APP", f"Student opened {p} during exam"))
                else:
                    # App left foreground — reset its grace timer
                    _app_first_seen.pop(f"proc:{fg_proc_name}", None)

            # ── BACKGROUND PROCESS scan (DISABLED for foreground-only logic)
            # We deliberately do NOT scan all running processes anymore.
            # Only the FOREGROUND window is checked above.
            # This prevents crash handlers, updaters, notifications from striking.

# ══════════════════════════════════════════════════════════════════════════════
#  CAMERA HUB  (exam mode — hidden from student, seen by proctor)
# ══════════════════════════════════════════════════════════════════════════════
class CameraHub:
    MAX_STRIKES   = 5
    WARNING_SECS  = 4.0
    GAZE_FRAMES   = 15
    GAZE_DIRS     = {"left","right","up","down"}
    MULTI_GRACE   = 1.5
    YOLO_INTERVAL = 5

    def __init__(self, student_id):
        self.student_id     = student_id
        self.latest_frame   = None
        self.running        = True
        self.violations     = []
        self.strike_count   = 0
        self.face_count     = 0
        self.gaze_dir       = "center"
        self.phone_detected = False
        self.terminated     = False
        self._lock          = threading.Lock()
        self._thread        = threading.Thread(target=self._run, daemon=True)

    def start(self):  self._thread.start()
    def stop(self):   self.running = False

    def get_frame(self):
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def add_strike(self, event, detail=""):
        """Called externally (SecurityMonitor) to add a strike."""
        self.strike_count += 1
        self._log(f"STRIKE {self.strike_count}", detail or event)

    def _log(self, event, detail=""):
        ts  = time.strftime("%H:%M:%S")
        msg = f"[{ts}] {event}: {detail}"
        with self._lock:
            self.violations.append(msg)
            if len(self.violations) > 400:
                self.violations = self.violations[-400:]
        db_log_violation(self.student_id, event, detail)
        print(msg)

    def _run(self):
        from gaze_tracking import GazeTracking
        yolo      = YOLO("yolov8n.pt")
        face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=4,
            min_detection_confidence=0.92,
            min_tracking_confidence=0.92)
        gaze = GazeTracking()
        cap  = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        phone_t=None; multi_t=None; gaze_streak=0; gaze_timer=None
        frame_n=0; last_boxes=[]

        self._log("EXAM_START", self.student_id)
        print(f"[✅ EXAM START] {self.student_id} | Camera hidden from student")

        while self.running:
            ret, frame = cap.read()
            if not ret: break
            frame_n += 1

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = face_mesh.process(rgb)
            fc  = 0
            if res.multi_face_landmarks:
                h_f,w_f = frame.shape[:2]
                for fl in res.multi_face_landmarks:
                    xs=[lm.x for lm in fl.landmark]
                    if max(xs)-min(xs)>=0.14:
                        fc+=1
                        for lm in fl.landmark[::5]:
                            cv2.circle(frame,(int(lm.x*w_f),int(lm.y*h_f)),1,(0,200,100),-1)

            gaze.refresh(frame)
            gd = gaze.direction()
            if gaze.pupils_located:
                for coords in [gaze.pupil_left_coords(),gaze.pupil_right_coords()]:
                    if coords: cv2.circle(frame,coords,4,(0,255,120),-1)

            if frame_n % self.YOLO_INTERVAL == 0:
                det = yolo(frame,verbose=False)[0]; last_boxes=[]
                for box in det.boxes:
                    if yolo.names[int(box.cls[0])]=="cell phone" and float(box.conf[0])>0.45:
                        x1,y1,x2,y2=map(int,box.xyxy[0])
                        last_boxes.append((x1,y1,x2,y2,float(box.conf[0])))
            for x1,y1,x2,y2,cf in last_boxes:
                cv2.rectangle(frame,(x1,y1),(x2,y2),(0,60,255),2)
                cv2.putText(frame,f"PHONE {cf:.0%}",(x1,y1-8),cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,60,255),2)

            # Gaze strike
            if gaze.calibration.is_complete() and gd in self.GAZE_DIRS:
                gaze_streak+=1
                if gaze_streak>=self.GAZE_FRAMES:
                    if gaze_timer is None:
                        gaze_timer=time.time(); self._log("GAZE_WARNING",f"Looking {gd}")
                    elif time.time()-gaze_timer>=self.WARNING_SECS:
                        self.strike_count+=1
                        self._log(f"STRIKE {self.strike_count}",f"Gaze away ({gd})")
                        gaze_timer=time.time()
            else:
                gaze_streak=0; gaze_timer=None

            # Multi-face
            if fc>1:
                cv2.putText(frame,"MULTIPLE FACES",(50,110),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,140,255),2)
                if multi_t is None: multi_t=time.time()
                elif time.time()-multi_t>=self.MULTI_GRACE:
                    self.strike_count+=1
                    self._log(f"STRIKE {self.strike_count}",f"Multiple faces ({fc})")
                    multi_t=time.time()
            else: multi_t=None

            # Phone
            if last_boxes:
                if phone_t is None:
                    phone_t=time.time(); self.strike_count+=1
                    self._log(f"STRIKE {self.strike_count}","Phone detected")
            else: phone_t=None

            # HUD
            h,w=frame.shape[:2]
            ov=frame.copy(); cv2.rectangle(ov,(0,0),(w,68),(15,15,15),-1)
            cv2.addWeighted(ov,0.75,frame,0.25,0,frame)
            cv2.putText(frame,f"ID:{self.student_id}",(10,22),cv2.FONT_HERSHEY_DUPLEX,0.55,(180,180,180),1)
            cv2.putText(frame,f"Faces:{fc}",(10,48),cv2.FONT_HERSHEY_DUPLEX,0.55,
                        (80,220,80) if fc==1 else (0,80,255),1)
            cv2.putText(frame,f"Gaze:{gd}",(w//2-80,22),cv2.FONT_HERSHEY_DUPLEX,0.55,
                        (80,220,80) if gd=="center" else (0,180,255),1)
            sc_c=(0,220,80) if self.strike_count==0 else (0,160,255) if self.strike_count<4 else (0,50,255)
            cv2.putText(frame,f"Strikes:{self.strike_count}/{self.MAX_STRIKES}",
                        (w-220,22),cv2.FONT_HERSHEY_DUPLEX,0.55,sc_c,1)

            if self.strike_count>=self.MAX_STRIKES:
                overlay=np.zeros_like(frame); overlay[:]=( 0,0,160)
                cv2.addWeighted(overlay,0.85,frame,0.15,0,frame)
                cv2.putText(frame,"EXAM TERMINATED",(w//2-210,h//2),
                            cv2.FONT_HERSHEY_DUPLEX,1.4,(255,255,255),3)
                self._log("EXAM_TERMINATED","Max strikes reached")
                self.terminated=True
                with self._lock: self.latest_frame=frame.copy()
                break

            with self._lock:
                self.latest_frame=frame.copy()
                self.face_count=fc; self.gaze_dir=gd
                self.phone_detected=bool(last_boxes)

        cap.release(); face_mesh.close()
        print(f"[CameraHub] Stopped — {self.student_id}")

# ══════════════════════════════════════════════════════════════════════════════
#  INTERVIEW CAMERA HUB  (both cameras open, bidirectional like Google Meet)
# ══════════════════════════════════════════════════════════════════════════════
class InterviewHub:
    """
    Opens two camera feeds simultaneously.
    cam_idx_student (0) = student camera
    cam_idx_proctor (1) = interviewer camera (if available, else mirrors student)
    Both sides see both feeds.
    Also runs proctoring checks on the student camera.
    """
    MAX_STRIKES   = 5
    GAZE_FRAMES   = 15
    WARNING_SECS  = 4.0
    GAZE_DIRS     = {"left","right","up","down"}
    MULTI_GRACE   = 2.0

    def __init__(self, student_id):
        self.student_id      = student_id
        self.student_frame   = None   # student camera annotated
        self.proctor_frame   = None   # interviewer camera
        self.running         = True
        self.violations      = []
        self.strike_count    = 0
        self.face_count      = 0
        self.gaze_dir        = "center"
        self.terminated      = False
        self._lock           = threading.Lock()
        self._thread         = threading.Thread(target=self._run, daemon=True)

    def start(self):  self._thread.start()
    def stop(self):   self.running = False

    def get_student_frame(self):
        with self._lock:
            return self.student_frame.copy() if self.student_frame is not None else None

    def get_proctor_frame(self):
        with self._lock:
            return self.proctor_frame.copy() if self.proctor_frame is not None else None

    def add_strike(self, event, detail=""):
        self.strike_count+=1; self._log(f"STRIKE {self.strike_count}", detail or event)

    def _log(self, event, detail=""):
        ts=time.strftime("%H:%M:%S"); msg=f"[{ts}] {event}: {detail}"
        with self._lock:
            self.violations.append(msg)
            if len(self.violations)>400: self.violations=self.violations[-400:]
        db_log_violation(self.student_id, event, detail); print(msg)

    def _run(self):
        from gaze_tracking import GazeTracking
        face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=4, min_detection_confidence=0.9, min_tracking_confidence=0.9)
        gaze = GazeTracking()

        cap_s = cv2.VideoCapture(0)
        cap_s.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap_s.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        # No second local camera — proctor sends their frame via /push_proctor_frame
        # We just build a waiting placeholder until the first push arrives
        h_ph, w_ph = 480, 640
        _placeholder = np.zeros((h_ph, w_ph, 3), dtype=np.uint8)
        cv2.putText(_placeholder, "Waiting for interviewer camera...",
                    (30, h_ph//2 - 20), cv2.FONT_HERSHEY_DUPLEX, 0.7, (80, 80, 180), 2)
        cv2.putText(_placeholder, "Proctor: open proctor_client.py",
                    (30, h_ph//2 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 60, 140), 1)

        gaze_streak=0; gaze_timer=None; multi_t=None
        self._log("INTERVIEW_START", self.student_id)
        print(f"[🎥 INTERVIEW START] {self.student_id} | Student cam active, waiting for proctor cam")

        while self.running:
            ret_s, frame_s = cap_s.read()
            if not ret_s: break

            # Proctor frame: use whatever was last pushed via /push_proctor_frame
            # If nothing pushed yet, use the waiting placeholder
            with self._lock:
                frame_p = self.proctor_frame.copy() if self.proctor_frame is not None else _placeholder.copy()

            # ── proctoring on student frame ──────────────────────────
            rgb = cv2.cvtColor(frame_s, cv2.COLOR_BGR2RGB)
            res = face_mesh.process(rgb)
            fc  = 0
            if res.multi_face_landmarks:
                h_f,w_f=frame_s.shape[:2]
                for fl in res.multi_face_landmarks:
                    xs=[lm.x for lm in fl.landmark]
                    if max(xs)-min(xs)>=0.14:
                        fc+=1
                        for lm in fl.landmark[::5]:
                            cv2.circle(frame_s,(int(lm.x*w_f),int(lm.y*h_f)),1,(0,200,100),-1)

            gaze.refresh(frame_s)
            gd=gaze.direction()
            if gaze.pupils_located:
                for coords in [gaze.pupil_left_coords(),gaze.pupil_right_coords()]:
                    if coords: cv2.circle(frame_s,coords,4,(0,255,120),-1)

            if gaze.calibration.is_complete() and gd in self.GAZE_DIRS:
                gaze_streak+=1
                if gaze_streak>=self.GAZE_FRAMES:
                    if gaze_timer is None:
                        gaze_timer=time.time(); self._log("GAZE_WARNING",f"Looking {gd}")
                    elif time.time()-gaze_timer>=self.WARNING_SECS:
                        self.strike_count+=1
                        self._log(f"STRIKE {self.strike_count}",f"Gaze away ({gd})")
                        gaze_timer=time.time()
            else:
                gaze_streak=0; gaze_timer=None

            if fc>1:
                if multi_t is None: multi_t=time.time()
                elif time.time()-multi_t>=self.MULTI_GRACE:
                    self.strike_count+=1
                    self._log(f"STRIKE {self.strike_count}",f"Multiple faces ({fc})")
                    multi_t=time.time()
            else: multi_t=None

            # HUD on student frame
            h,w=frame_s.shape[:2]
            ov=frame_s.copy(); cv2.rectangle(ov,(0,0),(w,60),(10,10,10),-1)
            cv2.addWeighted(ov,0.75,frame_s,0.25,0,frame_s)
            cv2.putText(frame_s,f"STUDENT: {self.student_id}",(10,20),
                        cv2.FONT_HERSHEY_DUPLEX,0.55,(180,255,180),1)
            cv2.putText(frame_s,f"Gaze:{gd} | Faces:{fc} | Strikes:{self.strike_count}/{self.MAX_STRIKES}",
                        (10,45),cv2.FONT_HERSHEY_DUPLEX,0.45,
                        (80,220,80) if self.strike_count==0 else (0,150,255),1)

            if self.strike_count>=self.MAX_STRIKES:
                overlay=np.zeros_like(frame_s); overlay[:]=(0,0,160)
                cv2.addWeighted(overlay,0.85,frame_s,0.15,0,frame_s)
                cv2.putText(frame_s,"INTERVIEW TERMINATED",(w//2-240,h//2),
                            cv2.FONT_HERSHEY_DUPLEX,1.2,(255,255,255),3)
                self._log("INTERVIEW_TERMINATED","Max strikes reached")
                self.terminated=True
                with self._lock:
                    self.student_frame=frame_s.copy()
                    self.proctor_frame=frame_p.copy()
                break

            with self._lock:
                self.student_frame=frame_s.copy()
                # Note: don't overwrite proctor_frame here — it's written by Flask push endpoint
                self.face_count=fc; self.gaze_dir=gd

        cap_s.release()
        face_mesh.close()
        print(f"[InterviewHub] Stopped — {self.student_id}")

# Global hubs
_hub:       CameraHub    = None
_iv_hub:    InterviewHub = None

# ══════════════════════════════════════════════════════════════════════════════
#  PARTICLE
# ══════════════════════════════════════════════════════════════════════════════
class Particle:
    def __init__(self, w, h, colors):
        self.canvas_w=w; self.canvas_h=h; self.reset(colors)
    def reset(self, colors):
        self.x=random.uniform(0,self.canvas_w); self.y=random.uniform(0,self.canvas_h)
        self.size=random.uniform(1.5,4.5); self.color=random.choice(colors)
        self.vx=random.uniform(-0.4,0.4); self.vy=random.uniform(-0.4,0.4)
        self.pulse=random.uniform(0,math.pi*2); self.pulse_speed=random.uniform(0.02,0.06)
    def update(self, mx, my):
        dx,dy=self.x-mx,self.y-my; dist=math.sqrt(dx*dx+dy*dy) or 1
        if dist<100:
            f=(100-dist)/100*1.2; self.vx+=dx/dist*f; self.vy+=dy/dist*f
        self.vx*=0.97; self.vy*=0.97
        sp=math.sqrt(self.vx**2+self.vy**2)
        if sp>2.5: self.vx=self.vx/sp*2.5; self.vy=self.vy/sp*2.5
        self.x+=self.vx; self.y+=self.vy; self.pulse+=self.pulse_speed
        if self.x<0 or self.x>self.canvas_w: self.vx*=-1; self.x=max(0,min(self.canvas_w,self.x))
        if self.y<0 or self.y>self.canvas_h: self.vy*=-1; self.y=max(0,min(self.canvas_h,self.y))

# ══════════════════════════════════════════════════════════════════════════════
#  BASE ANIMATED WINDOW
# ══════════════════════════════════════════════════════════════════════════════
class BaseWindow:
    def __init__(self, root, theme):
        self.root=root; self.theme=theme
        self.mouse_x=260; self.mouse_y=300; self.animating=True
        self.canvas=tk.Canvas(root,highlightthickness=0)
        self.canvas.place(x=0,y=0,relwidth=1,relheight=1)
        self.particles=[Particle(520,640,theme["particle_colors"]) for _ in range(55)]
        self.root.bind("<Configure>",self._on_resize)
        self.canvas.bind("<Motion>",lambda e:(setattr(self,'mouse_x',e.x),setattr(self,'mouse_y',e.y)))

    def _fade(self, hex_color, alpha):
        bg=self.theme["bg"].lstrip("#"); fg=hex_color.lstrip("#")
        try:
            br,bg_c,bb=int(bg[0:2],16),int(bg[2:4],16),int(bg[4:6],16)
            fr,fg_c,fb=int(fg[0:2],16),int(fg[2:4],16),int(fg[4:6],16)
            a=alpha/255
            return f"#{int(br+(fr-br)*a):02x}{int(bg_c+(fg_c-bg_c)*a):02x}{int(bb+(fb-bb)*a):02x}"
        except: return hex_color

    def _draw_particles(self):
        self.canvas.delete("particle")
        for p in self.particles:
            p.update(self.mouse_x,self.mouse_y)
            r=p.size+math.sin(p.pulse)*1.2
            self.canvas.create_oval(p.x-r,p.y-r,p.x+r,p.y+r,fill=p.color,outline="",tags="particle")
        for i,p1 in enumerate(self.particles):
            for p2 in self.particles[i+1:]:
                dx,dy=p1.x-p2.x,p1.y-p2.y; d=math.sqrt(dx*dx+dy*dy)
                if d<90:
                    op=int(255*(1-d/90)*0.35)
                    self.canvas.create_line(p1.x,p1.y,p2.x,p2.y,
                        fill=self._fade(p1.color,op),width=0.8,tags="particle")

    def _draw_card(self):
        self.canvas.delete("card_bg")
        w,h=self.root.winfo_width(),self.root.winfo_height()
        px=max(40,int(w*0.10)); x0,y0=px,max(70,int(h*0.11)); x1,y1=w-px,h-max(36,int(h*0.06))
        r=18; fill=self.theme["card_bg"]; ol=self.theme["card_border"]; t="card_bg"
        self.canvas.create_rectangle(x0+4,y0+4,x1+4,y1+4,fill="#000000",outline="",tags=t)
        self.canvas.create_rectangle(x0+r,y0,x1-r,y1,fill=fill,outline="",tags=t)
        self.canvas.create_rectangle(x0,y0+r,x1,y1-r,fill=fill,outline="",tags=t)
        for cx,cy,s,e in [(x0+r,y0+r,180,270),(x1-r,y0+r,270,360),(x0+r,y1-r,90,180),(x1-r,y1-r,0,90)]:
            self.canvas.create_arc(cx-r,cy-r,cx+r,cy+r,start=s,extent=e-s,fill=fill,outline="",tags=t)
        for c in [(x0+r,y0,x1-r,y0+2),(x0+r,y1-2,x1-r,y1),(x0,y0+r,x0+2,y1-r),(x1-2,y0+r,x1,y1-r)]:
            self.canvas.create_rectangle(*c,fill=ol,outline="",tags=t)

    def _animate(self):
        if not self.animating: return
        try:
            if not self.root.winfo_exists(): return
            w,h=self.root.winfo_width(),self.root.winfo_height()
            self.canvas.configure(bg=self.theme["canvas_bg"],width=w,height=h)
            self._draw_particles(); self._draw_card()
            self.root.after(30,self._animate)
        except Exception:
            self.animating = False

    def _on_resize(self, event=None):
        w,h=self.root.winfo_width(),self.root.winfo_height()
        if w<10 or h<10: return
        self.canvas.config(width=w,height=h)
        if hasattr(self,'ui_frame'):
            px=max(40,int(w*0.10)); cw=w-2*px
            fw=min(cw-20,420)
            self.ui_frame.place(x=px+(cw-fw)//2,
                                y=max(70,int(h*0.11))+max(18,int(h*0.04)),width=fw)
        t=max(55,min(120,int(w*h/8000)))
        while len(self.particles)<t: self.particles.append(Particle(w,h,self.theme["particle_colors"]))
        while len(self.particles)>t: self.particles.pop()
        for p in self.particles:
            p.canvas_w=w; p.canvas_h=h
            if p.x>w or p.y>h: p.x=random.uniform(0,w); p.y=random.uniform(0,h)

    def _make_entry(self, parent, show=None):
        fr=tk.Frame(parent,bg=self.theme["entry_border"],bd=0)
        fr.pack(fill="x",padx=30,pady=(3,0))
        e=tk.Entry(fr,font=("Helvetica",11),bg=self.theme["entry_bg"],fg=self.theme["entry_fg"],
                   insertbackground=self.theme["entry_fg"],bd=0,relief="flat",show=show or "")
        e.pack(fill="x",padx=1,pady=1,ipady=8)
        e.bind("<FocusIn>",lambda _: fr.configure(bg=self.theme["entry_focus"]))
        e.bind("<FocusOut>",lambda _: fr.configure(bg=self.theme["entry_border"]))
        return e

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LOGIN  (role: Student / Proctor  ×  mode: Exam / Interview)
# ══════════════════════════════════════════════════════════════════════════════
class MainLogin(BaseWindow):
    def __init__(self):
        self.root=tk.Tk()
        self.root.title("ExamShield v2 — Login")
        self.root.geometry("540x700"); self.root.resizable(True,True); self.root.minsize(440,600)
        self.is_dark=True; self.theme=DARK
        self.role=tk.StringVar(value="student")
        self.mode=tk.StringVar(value="exam")     # "exam" or "interview"
        super().__init__(self.root,self.theme)
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW",self._close)
        self._animate()

    def _build_ui(self):
        t=self.theme
        self.ui_frame=tk.Frame(self.root,bg=t["card_bg"],bd=0,highlightthickness=0)
        self.ui_frame.place(x=70,y=110,width=400)

        # Logo
        tk.Label(self.ui_frame,text="🛡️",font=("Segoe UI Emoji",28),bg=t["card_bg"]).pack(pady=(16,0))
        tk.Label(self.ui_frame,text="ExamShield",font=("Helvetica",20,"bold"),
                 bg=t["card_bg"],fg=t["title_fg"]).pack()
        tk.Label(self.ui_frame,text="Secure AI Assessment Platform",
                 font=("Helvetica",9),bg=t["card_bg"],fg=t["subtitle_fg"]).pack(pady=(2,12))

        # ── Mode selector: EXAM | INTERVIEW ────────────────────────
        tk.Label(self.ui_frame,text="SESSION TYPE",font=("Helvetica",8,"bold"),
                 bg=t["card_bg"],fg=t["subtitle_fg"]).pack(pady=(0,4))
        mf=tk.Frame(self.ui_frame,bg=t["card_bg"]); mf.pack(pady=(0,10))
        self.btn_exam=tk.Button(mf,text="📝  Exam",font=("Helvetica",10,"bold"),
            bd=0,relief="flat",cursor="hand2",width=13,command=lambda:self._set_mode("exam"))
        self.btn_exam.grid(row=0,column=0,padx=3,ipady=6)
        self.btn_iv=tk.Button(mf,text="🎙  Interview",font=("Helvetica",10,"bold"),
            bd=0,relief="flat",cursor="hand2",width=13,command=lambda:self._set_mode("interview"))
        self.btn_iv.grid(row=0,column=1,padx=3,ipady=6)

        # ── Role selector: Student | Proctor ───────────────────────
        tk.Label(self.ui_frame,text="LOGIN AS",font=("Helvetica",8,"bold"),
                 bg=t["card_bg"],fg=t["subtitle_fg"]).pack(pady=(4,4))
        pf=tk.Frame(self.ui_frame,bg=t["card_bg"]); pf.pack(pady=(0,10))
        self.pill_s=tk.Button(pf,text="👨‍🎓  Student",font=("Helvetica",10,"bold"),
            bd=0,relief="flat",cursor="hand2",width=13,command=lambda:self._set_role("student"))
        self.pill_s.grid(row=0,column=0,padx=3,ipady=6)
        self.pill_p=tk.Button(pf,text="👨‍🏫  Proctor",font=("Helvetica",10,"bold"),
            bd=0,relief="flat",cursor="hand2",width=13,command=lambda:self._set_role("proctor"))
        self.pill_p.grid(row=0,column=1,padx=3,ipady=6)

        # Fields
        self.lbl_id=tk.Label(self.ui_frame,font=("Helvetica",10,"bold"),
                              bg=t["card_bg"],fg=t["label_fg"],anchor="w")
        self.lbl_id.pack(fill="x",padx=30,pady=(6,0))
        self.eid=self._make_entry(self.ui_frame)

        tk.Label(self.ui_frame,text="Password",font=("Helvetica",10,"bold"),
                 bg=t["card_bg"],fg=t["label_fg"],anchor="w").pack(fill="x",padx=30,pady=(8,0))
        self.epw=self._make_entry(self.ui_frame,show="●")

        # Buttons
        bf=tk.Frame(self.ui_frame,bg=t["card_bg"]); bf.pack(pady=14)
        self.btn_login=tk.Button(bf,text="Log In ▶",font=("Helvetica",11,"bold"),
            bd=0,relief="flat",cursor="hand2",width=12,command=self._login)
        self.btn_login.grid(row=0,column=0,padx=6,ipady=6)
        self.btn_reg=tk.Button(bf,text="Register ✚",font=("Helvetica",11,"bold"),
            bd=0,relief="flat",cursor="hand2",width=12,command=self._register)
        self.btn_reg.grid(row=0,column=1,padx=6,ipady=6)

        # Theme toggle
        self.btn_tog=tk.Button(self.root,font=("Helvetica",9),bd=0,relief="flat",
            cursor="hand2",command=self._toggle)
        self.btn_tog.place(x=375,y=55,width=140,height=28)

        self._set_mode("exam"); self._set_role("student"); self._apply()

    def _set_mode(self, m):
        self.mode.set(m); t=self.theme
        exam_col  = t["btn_primary_bg"] if m=="exam" else t["pill_inactive_bg"]
        exam_fg   = t["btn_primary_fg"] if m=="exam" else t["pill_inactive_fg"]
        iv_col    = t["interview_accent"] if m=="interview" else t["pill_inactive_bg"]
        iv_fg     = "#0d1117"  if m=="interview" else t["pill_inactive_fg"]
        self.btn_exam.configure(bg=exam_col, fg=exam_fg)
        self.btn_iv.configure(bg=iv_col, fg=iv_fg)

    def _set_role(self, r):
        self.role.set(r); t=self.theme
        if r=="student":
            self.pill_s.configure(bg=t["student_accent"],fg=t["pill_active_fg"])
            self.pill_p.configure(bg=t["pill_inactive_bg"],fg=t["pill_inactive_fg"])
            self.lbl_id.configure(text="Student ID")
            self.btn_reg.configure(state="normal",bg=t["btn_secondary_bg"],fg=t["btn_secondary_fg"])
        else:
            self.pill_p.configure(bg=t["proctor_accent"],fg=t["pill_active_fg"])
            self.pill_s.configure(bg=t["pill_inactive_bg"],fg=t["pill_inactive_fg"])
            self.lbl_id.configure(text="Proctor ID")
            self.btn_reg.configure(state="disabled",bg=t["pill_inactive_bg"],fg=t["pill_inactive_fg"])

    def _apply(self):
        t=self.theme; self.root.configure(bg=t["bg"])
        self.btn_login.configure(bg=t["btn_primary_bg"],fg=t["btn_primary_fg"])
        self.btn_tog.configure(bg=t["btn_toggle_bg"],fg=t["btn_toggle_fg"],
                                text=f"{t['mode_icon']}  {t['mode_text']}")
        for e in [self.eid,self.epw]:
            e.configure(bg=t["entry_bg"],fg=t["entry_fg"],insertbackground=t["entry_fg"])
            e.master.configure(bg=t["entry_border"])
        self._set_mode(self.mode.get()); self._set_role(self.role.get())

    def _toggle(self):
        self.is_dark=not self.is_dark; self.theme=DARK if self.is_dark else LIGHT
        for p in self.particles: p.color=random.choice(self.theme["particle_colors"])
        self._apply()

    def _register(self):
        uid=self.eid.get().strip(); pwd=self.epw.get().strip()
        if not uid or not pwd: messagebox.showerror("Error","Fill both fields"); return
        if db_register(uid,pwd):
            try:
                from face_auth import capture_face_registration
                messagebox.showinfo("Face Registration",
                    f"Account '{uid}' created!\nNow register your face. Click OK when ready.")
                self.root.withdraw(); capture_face_registration(uid); self.root.deiconify()
            except ImportError: pass
            messagebox.showinfo("Success","Registered! You can now log in.")
        else:
            messagebox.showerror("Error","ID already exists.")

    def _login(self):
        global _hub, _iv_hub
        uid=self.eid.get().strip(); pwd=self.epw.get().strip()
        if not uid or not pwd: messagebox.showerror("Error","Fill both fields"); return
        role=self.role.get(); mode=self.mode.get()
        if not db_get_user(uid,pwd,role):
            messagebox.showerror("Login Failed","Wrong ID or password."); return

        if role=="student":
            # Face verification
            try:
                from face_auth import verify_face
                self.root.withdraw(); ok=verify_face(uid); self.root.deiconify()
                if not ok: messagebox.showerror("Denied","Face verification failed!"); return
            except ImportError: pass

            if mode=="exam":
                _hub=CameraHub(uid); _hub.start()
                messagebox.showinfo("Verified",f"Welcome {uid}!\nExam starting with security monitoring.")
                self.animating=False; self.root.destroy()
                ExamWindow(uid).run()
            else:
                _iv_hub=InterviewHub(uid); _iv_hub.start()
                messagebox.showinfo("Verified",f"Welcome {uid}!\nInterview starting — both cameras active.")
                self.animating=False; self.root.destroy()
                InterviewStudentWindow(uid).run()
        else:
            # Proctor login — no face verification needed
            self.animating=False; self.root.destroy()
            ProctorWindow(uid, mode, self.is_dark).run()

    def _close(self): self.animating=False; self.root.destroy()
    def run(self): self.root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
#  EXAM WINDOW  (student — MCQ, camera hidden, full security active)
# ══════════════════════════════════════════════════════════════════════════════
class ExamWindow:
    def __init__(self, student_id):
        self.sid=student_id
        qs=db_get_questions()
        random.shuffle(qs)         # ⑤ randomise question order
        self.qs=qs
        self.qi=0; self.answers={}; self.start=time.time()
        self.root=tk.Tk()
        self.root.title("ExamShield — Exam in Progress 🔒")
        self.root.geometry("860x680"); self.root.resizable(True,True)
        self.root.minsize(660,540); self.root.configure(bg="#0d1117")
        # Force fullscreen-ish to make tab-switch obvious
        self.root.state("zoomed") if platform.system()=="Windows" else None
        self.root.protocol("WM_DELETE_WINDOW",self._close)
        self._build()
        # Security monitor
        self._sec=SecurityMonitor(self.root, student_id, self._on_security_event)
        self._sec.start()
        # Bind focus loss
        self.root.bind("<FocusOut>", self._on_focus_out)
        self.root.bind("<FocusIn>",  self._on_focus_in)
        self._focus_lost_time=None
        self._tick()
        self._check_termination()

    def _on_security_event(self, event, detail):
        """Called by SecurityMonitor for tab-switch, app-block, keystroke."""
        # APP_WARNING = grace-period notice — log only, NO strike yet
        if event == "APP_WARNING":
            if _hub: _hub._log("APP_WARNING", detail)
            self._flash_warning(f"🔔 {detail}", color="#4a3800", duration=2000)
            return
        # KEYSTROKE = blocked but no strike (key already suppressed)
        if event == "KEYSTROKE":
            if _hub: _hub._log("KEYSTROKE_BLOCKED", detail)
            self._flash_warning(f"🚫 {detail}", color="#1a1a4a", duration=1500)
            return
        # Everything else (BLOCKED_APP, TAB_SWITCH) = real strike
        if _hub:
            _hub.add_strike(event, detail)
        self._flash_warning(f"⚠ STRIKE: {detail}")

    def _flash_warning(self, msg, color="#6a0000", duration=2500):
        try:
            w=tk.Toplevel(self.root); w.overrideredirect(True)
            w.configure(bg=color)
            w.geometry(f"520x56+{self.root.winfo_x()+130}+{self.root.winfo_y()+8}")
            tk.Label(w,text=msg,font=("Helvetica",10,"bold"),bg=color,fg="#ffffff",
                     wraplength=500).pack(expand=True)
            w.after(duration, w.destroy)
        except Exception: pass

    def _on_focus_out(self, event):
        self._focus_lost_time=time.time()

    def _on_focus_in(self, event):
        if self._focus_lost_time:
            lost=time.time()-self._focus_lost_time
            if lost>0.5:   # ignore brief flickers
                self._on_security_event("TAB_SWITCH",f"Window lost focus for {lost:.1f}s")
            self._focus_lost_time=None

    def _check_termination(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return
        if _hub and _hub.terminated:
            self._force_terminate()
            return
        self.root.after(500, self._check_termination)

    def _force_terminate(self):
        self._sec.stop()
        self.root.configure(bg="#1a0000")
        for w in self.root.winfo_children(): w.destroy()
        tk.Label(self.root,text="🚫",font=("Segoe UI Emoji",60),bg="#1a0000").pack(pady=(80,0))
        tk.Label(self.root,text="EXAM TERMINATED",font=("Helvetica",26,"bold"),
                 bg="#1a0000",fg="#ff4444").pack(pady=10)
        tk.Label(self.root,text="You reached 5 strikes.\nYour session has been recorded.",
                 font=("Helvetica",12),bg="#1a0000",fg="#c9d1d9").pack()
        tk.Button(self.root,text="Close",font=("Helvetica",11,"bold"),bg="#333",fg="#fff",
            bd=0,relief="flat",cursor="hand2",command=self.root.destroy).pack(pady=30,ipady=8,padx=60,fill="x")

    def _build(self):
        # Top bar
        bar=tk.Frame(self.root,bg="#161b22",height=56); bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Label(bar,text="🛡️  ExamShield — EXAM MODE  🔒",font=("Helvetica",13,"bold"),
                 bg="#161b22",fg="#58d6d6").pack(side="left",padx=16,pady=12)
        self.lbl_timer=tk.Label(bar,text="⏱ 00:00",font=("Helvetica",11,"bold"),
                                 bg="#161b22",fg="#0be881")
        self.lbl_timer.pack(side="right",padx=16)
        self.lbl_prog=tk.Label(bar,font=("Helvetica",10),bg="#161b22",fg="#8b949e")
        self.lbl_prog.pack(side="right",padx=8)

        # Strike bar
        self.strike_bar=tk.Frame(self.root,bg="#0d1117",height=28)
        self.strike_bar.pack(fill="x"); self.strike_bar.pack_propagate(False)
        self.lbl_strikes_disp=tk.Label(self.strike_bar,
            text="● Secure  |  Warnings: 0/5",
            font=("Helvetica",8),bg="#0d1117",fg="#2a2a3a")
        self.lbl_strikes_disp.pack(side="left",padx=14)
        tk.Label(self.strike_bar,text="🔒 Camera Active  |  Tab-Switch Monitored  |  Apps Blocked",
            font=("Helvetica",7),bg="#0d1117",fg="#1a3a1a").pack(side="right",padx=14)

        # Progress bar
        self.pbar=tk.Canvas(self.root,height=4,bg="#21262d",highlightthickness=0)
        self.pbar.pack(fill="x")

        # Main layout
        main=tk.Frame(self.root,bg="#0d1117"); main.pack(fill="both",expand=True)
        main.columnconfigure(1,weight=1); main.rowconfigure(0,weight=1)

        # Question nav strip
        ns=tk.Frame(main,bg="#161b22",width=100); ns.grid(row=0,column=0,sticky="nsew"); ns.pack_propagate(False)
        tk.Label(ns,text="Qs",font=("Helvetica",8,"bold"),bg="#161b22",fg="#8b949e").pack(pady=(10,4))
        self._qbtns=[]
        for i in range(len(self.qs)):
            b=tk.Button(ns,text=str(i+1),font=("Helvetica",8,"bold"),
                bg="#21262d",fg="#8b949e",bd=0,relief="flat",cursor="hand2",width=4,
                command=lambda idx=i:self._jump(idx))
            b.pack(pady=2,padx=8,ipady=3); self._qbtns.append(b)

        # Question area
        qf=tk.Frame(main,bg="#0d1117"); qf.grid(row=0,column=1,sticky="nsew")
        inner=tk.Frame(qf,bg="#0d1117"); inner.pack(fill="both",expand=True,padx=36,pady=18)

        self.lbl_qn=tk.Label(inner,font=("Helvetica",10,"bold"),bg="#0d1117",fg="#8b949e",anchor="w")
        self.lbl_qn.pack(fill="x",pady=(0,4))
        self.lbl_cat=tk.Label(inner,font=("Helvetica",8),bg="#0d1117",fg="#575fcf",anchor="w")
        self.lbl_cat.pack(fill="x",pady=(0,4))
        self.lbl_q=tk.Label(inner,font=("Helvetica",14,"bold"),bg="#0d1117",fg="#f0f6fc",
                              wraplength=580,justify="left",anchor="w")
        self.lbl_q.pack(fill="x",pady=(0,16))

        self.opt_var=tk.StringVar(); self.opt_btns=[]
        for opt in ["A","B","C","D"]:
            b=tk.Radiobutton(inner,variable=self.opt_var,value=opt,
                font=("Helvetica",12),bg="#161b22",fg="#c9d1d9",
                selectcolor="#0d3b2e",activebackground="#161b22",
                activeforeground="#0be881",indicatoron=True,
                bd=0,relief="flat",anchor="w",padx=16,pady=10,cursor="hand2")
            b.pack(fill="x",pady=3,ipady=4); self.opt_btns.append(b)

        self.lbl_marks=tk.Label(inner,font=("Helvetica",8),bg="#0d1117",fg="#ffd93d",anchor="e")
        self.lbl_marks.pack(fill="x",pady=(4,0))

        # Bottom nav
        nf=tk.Frame(self.root,bg="#0d1117"); nf.pack(pady=10)
        self.btn_prev=tk.Button(nf,text="◀ Prev",font=("Helvetica",11,"bold"),
            bg="#21262d",fg="#c9d1d9",bd=0,relief="flat",cursor="hand2",width=9,command=self._prev)
        self.btn_prev.grid(row=0,column=0,padx=5,ipady=6)
        self.btn_next=tk.Button(nf,text="Next ▶",font=("Helvetica",11,"bold"),
            bg="#575fcf",fg="#ffffff",bd=0,relief="flat",cursor="hand2",width=9,command=self._next)
        self.btn_next.grid(row=0,column=1,padx=5,ipady=6)
        self.btn_clr=tk.Button(nf,text="Clear",font=("Helvetica",10),
            bg="#21262d",fg="#ff6b9d",bd=0,relief="flat",cursor="hand2",width=7,command=self._clear)
        self.btn_clr.grid(row=0,column=2,padx=5,ipady=6)
        self.btn_sub=tk.Button(nf,text="Submit ✓",font=("Helvetica",11,"bold"),
            bg="#0be881",fg="#0d1117",bd=0,relief="flat",cursor="hand2",width=12,command=self._submit)
        self.btn_sub.grid(row=0,column=3,padx=5,ipady=6)
        self._load_q()

    def _load_q(self):
        if not self.qs: return
        q=self.qs[self.qi]; n=len(self.qs)
        self.lbl_qn.configure(text=f"Question {self.qi+1} of {n}")
        cat=q[8] if len(q)>8 else "General"
        self.lbl_cat.configure(text=f"📁 {cat}")
        self.lbl_q.configure(text=q[1])
        for i,b in enumerate(self.opt_btns):
            b.configure(text=f"  {'ABCD'[i]}.  {q[2+i]}",value="ABCD"[i])
        marks=q[7] if len(q)>7 else 1
        self.lbl_marks.configure(text=f"Marks: {marks}")
        self.opt_var.set(self.answers.get(self.qi,""))
        ratio=(self.qi+1)/n; w=self.root.winfo_width() or 860
        self.pbar.delete("all")
        self.pbar.create_rectangle(0,0,int(w*ratio),4,fill="#0be881",outline="")
        self.lbl_prog.configure(text=f"{self.qi+1}/{n}")
        self.btn_prev.configure(state="normal" if self.qi>0   else "disabled")
        self.btn_next.configure(state="normal" if self.qi<n-1 else "disabled")
        for i,b in enumerate(self._qbtns):
            if i==self.qi: b.configure(bg="#575fcf",fg="#ffffff")
            elif i in self.answers: b.configure(bg="#0be881",fg="#0d1117")
            else: b.configure(bg="#21262d",fg="#8b949e")

    def _save(self):
        a=self.opt_var.get()
        if a: self.answers[self.qi]=a

    def _jump(self,idx): self._save(); self.qi=idx; self._load_q()
    def _prev(self): self._save(); self.qi-=1; self._load_q()
    def _next(self): self._save(); self.qi+=1; self._load_q()
    def _clear(self):
        self.opt_var.set("")
        if self.qi in self.answers: del self.answers[self.qi]
        self._load_q()

    def _submit(self):
        self._save()
        un=len(self.qs)-len(self.answers)
        if un>0 and not messagebox.askyesno("Submit?",f"{un} unanswered. Submit anyway?"): return
        self._show_results()

    def _show_results(self):
        score=sum(1 for i,q in enumerate(self.qs) if self.answers.get(i)==q[6])
        total=len(self.qs); elapsed=int(time.time()-self.start)
        pct=int(score/total*100) if total else 0
        grade="A" if pct>=90 else "B" if pct>=75 else "C" if pct>=60 else "D" if pct>=40 else "F"

        # ① Snapshot strikes BEFORE stopping anything
        strikes = _hub.strike_count if _hub else 0

        # ② Stop security monitor and camera (order matters — sec first)
        try: self._sec.stop()
        except Exception: pass
        try:
            if _hub: _hub.stop()
        except Exception: pass

        # ③ Write CSV (use 'wr' so it never clashes with csv module name)
        log = f"{self.sid}_result.csv"
        try:
            with open(log, 'w', newline='', encoding='utf-8') as f:
                wr = csv.writer(f)
                wr.writerow(["Q#","Question","Your Answer","Correct","Result"])
                for i, q in enumerate(self.qs):
                    a = self.answers.get(i, "-")
                    wr.writerow([i+1, q[1], a, q[6], "OK" if a==q[6] else "X"])
        except Exception as e:
            print(f"[CSV] Save failed: {e}")

        # ④ Show popup — everything is stopped so no threading conflicts
        messagebox.showinfo("Exam Complete",
            f"Score  : {score}/{total} ({pct}%)\n"
            f"Grade  : {grade}\n"
            f"Time   : {elapsed//60:02d}:{elapsed%60:02d}\n"
            f"Strikes: {strikes}\n\n"
            f"Results saved → {log}")
        try: self.root.destroy()
        except Exception: pass

    def _tick(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return
        try:
            e=int(time.time()-self.start); m,s=e//60,e%60
            self.lbl_timer.configure(text=f"⏱ {m:02d}:{s:02d}")
            if _hub:
                sc=_hub.strike_count
                col="#2a2a3a" if sc==0 else "#6a3800" if sc<3 else "#6a0000"
                self.lbl_strikes_disp.configure(
                    text=f"● Secure  |  Warnings: {sc}/{CameraHub.MAX_STRIKES}",fg=col)
        except Exception:
            pass
        self.root.after(1000,self._tick)

    def _close(self):
        if messagebox.askyesno("Quit","Exit exam? All progress lost."):
            self._sec.stop()
            if _hub: _hub.stop()
            self.root.destroy()

    def run(self): self.root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
#  INTERVIEW STUDENT WINDOW  (both cameras visible to student AND proctor)
# ══════════════════════════════════════════════════════════════════════════════
class InterviewStudentWindow:
    """
    Student sees:
      - Their own camera (left panel)
      - Interviewer's camera (right panel)  → like Google Meet
      - A text chat / notes area
    Security still active (gaze + multi-face via InterviewHub).
    """
    def __init__(self, student_id):
        self.sid=student_id
        self.root=tk.Tk()
        self.root.title("ExamShield — Interview Mode 🎙")
        self.root.geometry("1100x680"); self.root.resizable(True,True)
        self.root.minsize(900,560); self.root.configure(bg="#0d1117")
        self.root.state("zoomed") if platform.system()=="Windows" else None
        self.root.protocol("WM_DELETE_WINDOW",self._close)
        # Security
        self._sec=SecurityMonitor(self.root, student_id, self._on_sec)
        self._sec.start()
        self.root.bind("<FocusOut>",self._focus_out)
        self.root.bind("<FocusIn>", self._focus_in)
        self._focus_lost=None
        self._build()
        self._poll_cam()
        self._tick()
        self._check_terminate()

    def _on_sec(self, event, detail):
        if event == "APP_WARNING":
            if _iv_hub: _iv_hub._log("APP_WARNING", detail)
            self._flash(f"🔔 {detail}", color="#4a3800", duration=2000)
            return
        if event == "KEYSTROKE":
            if _iv_hub: _iv_hub._log("KEYSTROKE_BLOCKED", detail)
            self._flash(f"🚫 {detail}", color="#1a1a4a", duration=1500)
            return
        if _iv_hub: _iv_hub.add_strike(event, detail)
        self._flash(f"⚠ STRIKE: {detail}")

    def _flash(self, msg, color="#6a0000", duration=2500):
        try:
            w=tk.Toplevel(self.root); w.overrideredirect(True)
            w.configure(bg=color)
            w.geometry(f"520x52+{self.root.winfo_x()+180}+{self.root.winfo_y()+6}")
            tk.Label(w,text=msg,font=("Helvetica",10,"bold"),bg=color,fg="#fff",
                     wraplength=500).pack(expand=True)
            w.after(duration, w.destroy)
        except Exception: pass

    def _focus_out(self,e): self._focus_lost=time.time()
    def _focus_in(self,e):
        if self._focus_lost:
            lost=time.time()-self._focus_lost
            if lost>0.5: self._on_sec("TAB_SWITCH",f"Focus lost {lost:.1f}s")
            self._focus_lost=None

    def _check_terminate(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return
        if _iv_hub and _iv_hub.terminated:
            self._force_end(); return
        self.root.after(500,self._check_terminate)

    def _force_end(self):
        self._sec.stop()
        for w in self.root.winfo_children(): w.destroy()
        self.root.configure(bg="#1a0000")
        tk.Label(self.root,text="🚫",font=("Segoe UI Emoji",60),bg="#1a0000").pack(pady=(80,0))
        tk.Label(self.root,text="INTERVIEW TERMINATED",font=("Helvetica",24,"bold"),
                 bg="#1a0000",fg="#ff4444").pack(pady=10)
        tk.Button(self.root,text="Close",font=("Helvetica",11,"bold"),bg="#333",fg="#fff",
            bd=0,relief="flat",cursor="hand2",command=self.root.destroy).pack(pady=30,ipady=8,padx=80,fill="x")

    def _build(self):
        # Top bar
        bar=tk.Frame(self.root,bg="#161b22",height=52); bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Label(bar,text="🎙  ExamShield — INTERVIEW MODE",font=("Helvetica",13,"bold"),
                 bg="#161b22",fg="#ffd93d").pack(side="left",padx=16,pady=12)
        self.lbl_timer=tk.Label(bar,text="⏱ 00:00",font=("Helvetica",11,"bold"),
                                 bg="#161b22",fg="#0be881")
        self.lbl_timer.pack(side="right",padx=16)
        self.lbl_status=tk.Label(bar,text="● Connected",font=("Helvetica",9),
                                  bg="#161b22",fg="#0be881")
        self.lbl_status.pack(side="right",padx=16)

        # Warn bar
        self.warn_bar=tk.Frame(self.root,bg="#0d1117",height=24); self.warn_bar.pack(fill="x"); self.warn_bar.pack_propagate(False)
        self.lbl_warn=tk.Label(self.warn_bar,text="● Monitoring active  |  Violations: 0/5",
            font=("Helvetica",7),bg="#0d1117",fg="#1a3a1a")
        self.lbl_warn.pack(side="left",padx=14)

        # Main: 3 columns — student cam | interviewer cam | chat
        main=tk.Frame(self.root,bg="#0d1117"); main.pack(fill="both",expand=True,padx=8,pady=6)
        main.columnconfigure(0,weight=2); main.columnconfigure(1,weight=2); main.columnconfigure(2,weight=1)
        main.rowconfigure(0,weight=1)

        # Student cam
        lcol=tk.Frame(main,bg="#0d1117"); lcol.grid(row=0,column=0,sticky="nsew",padx=(0,4))
        tk.Label(lcol,text="📹  Your Camera",font=("Helvetica",9,"bold"),
                 bg="#0d1117",fg="#58d6d6").pack(anchor="w",pady=(0,4))
        self.cam_self=tk.Label(lcol,bg="#0b0b13",text="Connecting camera…",
                                fg="#3a3a5a",font=("Helvetica",9))
        self.cam_self.pack(fill="both",expand=True)

        # Interviewer cam
        rcol=tk.Frame(main,bg="#0d1117"); rcol.grid(row=0,column=1,sticky="nsew",padx=4)
        tk.Label(rcol,text="📹  Interviewer Camera",font=("Helvetica",9,"bold"),
                 bg="#0d1117",fg="#ffd93d").pack(anchor="w",pady=(0,4))
        self.cam_pro=tk.Label(rcol,bg="#0b0b13",text="Connecting camera…",
                               fg="#3a3a5a",font=("Helvetica",9))
        self.cam_pro.pack(fill="both",expand=True)

        # Notes / chat panel
        ncol=tk.Frame(main,bg="#161b22"); ncol.grid(row=0,column=2,sticky="nsew",padx=(4,0))
        tk.Label(ncol,text="📝  Notes (read-only)",font=("Helvetica",9,"bold"),
                 bg="#161b22",fg="#8b949e").pack(anchor="w",padx=8,pady=(8,4))
        self.notes=tk.Text(ncol,font=("Helvetica",9),bg="#0d1117",fg="#c9d1d9",
                            bd=0,relief="flat",wrap="word",state="disabled")
        self.notes.pack(fill="both",expand=True,padx=6,pady=(0,8))
        # Notes are read-only for student — proctor types them
        tk.Label(ncol,text="Notes provided by interviewer",font=("Helvetica",7),
                 bg="#161b22",fg="#3a3a5a").pack(pady=(0,6))

    def _poll_cam(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return

        if _iv_hub:
            # ── Your camera (student) ────────────────────────────────
            try:
                sf = _iv_hub.get_student_frame()
                if sf is not None:
                    lw = max(self.cam_self.winfo_width(),  320)
                    lh = max(self.cam_self.winfo_height(), 240)
                    h, w = sf.shape[:2]
                    scale = min(lw/w, lh/h)
                    nw, nh = max(1,int(w*scale)), max(1,int(h*scale))
                    img = ImageTk.PhotoImage(
                        Image.fromarray(cv2.cvtColor(cv2.resize(sf,(nw,nh)), cv2.COLOR_BGR2RGB)))
                    self.cam_self.configure(image=img, text="")
                    self.cam_self.image = img   # hard ref — prevent GC
            except Exception as e:
                print(f"[student cam] {e}")

            # ── Interviewer camera (from proctor's machine via network) ──
            try:
                pf = _iv_hub.get_proctor_frame()
                if pf is not None:
                    lw = max(self.cam_pro.winfo_width(),  320)
                    lh = max(self.cam_pro.winfo_height(), 240)
                    h, w = pf.shape[:2]
                    scale = min(lw/w, lh/h)
                    nw, nh = max(1,int(w*scale)), max(1,int(h*scale))
                    img = ImageTk.PhotoImage(
                        Image.fromarray(cv2.cvtColor(cv2.resize(pf,(nw,nh)), cv2.COLOR_BGR2RGB)))
                    self.cam_pro.configure(image=img, text="")
                    self.cam_pro.image = img    # hard ref — prevent GC
                else:
                    self.cam_pro.configure(
                        image="",
                        text="Waiting for interviewer\nto connect their camera…",
                        fg="#3a3a5a")
            except Exception as e:
                print(f"[proctor cam] {e}")

        self.root.after(100, self._poll_cam)

    def _tick(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return
        try:
            if not hasattr(self,'_start'): self._start=time.time()
            e=int(time.time()-self._start); m,s=e//60,e%60
            self.lbl_timer.configure(text=f"⏱ {m:02d}:{s:02d}")
            if _iv_hub:
                sc=_iv_hub.strike_count
                col="#1a3a1a" if sc==0 else "#6a3800" if sc<3 else "#6a0000"
                self.lbl_warn.configure(
                    text=f"● Monitoring active  |  Violations: {sc}/{InterviewHub.MAX_STRIKES}",fg=col)
        except Exception:
            pass
        self.root.after(1000,self._tick)

    def _close(self):
        if messagebox.askyesno("Quit","End interview session?"):
            self._sec.stop()
            if _iv_hub: _iv_hub.stop()
            self.root.destroy()

    def run(self): self.root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
#  PROCTOR WINDOW  (unified: Exam mode tabs + Interview mode tabs)
# ══════════════════════════════════════════════════════════════════════════════
class ProctorWindow:
    def __init__(self, proctor_id, mode="exam", is_dark=True):
        self.pid=proctor_id; self.mode=mode; self.is_dark=is_dark
        self.theme=DARK if is_dark else LIGHT
        self.root=tk.Tk()
        self.root.title(f"ExamShield — Proctor Dashboard  [{proctor_id}]  {'📝 EXAM' if mode=='exam' else '🎙 INTERVIEW'}")
        self.root.geometry("1200x740"); self.root.resizable(True,True)
        self.root.minsize(1000,620); self.root.configure(bg="#0d1117")
        self.root.protocol("WM_DELETE_WINDOW",self._close)
        self._shared_notes="" # for interview note-passing
        self._build()
        self._poll_cam()
        self._poll_violations()

    def _build(self):
        t=self.theme
        # Top bar
        bar=tk.Frame(self.root,bg="#161b22",height=56); bar.pack(fill="x"); bar.pack_propagate(False)
        mode_icon="📝" if self.mode=="exam" else "🎙"
        mode_col="#ff6b9d" if self.mode=="exam" else "#ffd93d"
        tk.Label(bar,text=f"👨‍🏫  Proctor Dashboard  {mode_icon}",
                 font=("Helvetica",13,"bold"),bg="#161b22",fg=mode_col).pack(side="left",padx=16,pady=12)
        tk.Label(bar,text=f"│  {self.pid}",font=("Helvetica",10),bg="#161b22",fg="#8b949e").pack(side="left")
        tk.Button(bar,text="⬅ Logout",font=("Helvetica",9),bd=0,relief="flat",cursor="hand2",
            bg="#21262d",fg="#c9d1d9",command=self._logout).pack(side="right",padx=12,pady=10,ipady=4)
        self.btn_tog=tk.Button(bar,font=("Helvetica",9),bd=0,relief="flat",cursor="hand2",
            bg=t["btn_toggle_bg"],fg=t["btn_toggle_fg"],
            text=f"{t['mode_icon']}  {t['mode_text']}",command=self._toggle)
        self.btn_tog.pack(side="right",padx=4,pady=10)

        # Main layout
        main=tk.Frame(self.root,bg="#0d1117"); main.pack(fill="both",expand=True,padx=10,pady=6)
        main.columnconfigure(0,weight=3); main.columnconfigure(1,weight=2); main.rowconfigure(0,weight=1)

        # LEFT: camera panel
        left=tk.Frame(main,bg="#0d1117"); left.grid(row=0,column=0,sticky="nsew",padx=(0,8))
        left.rowconfigure(1,weight=1)

        if self.mode=="exam":
            tk.Label(left,text="📷  Student Camera (Live)",font=("Helvetica",10,"bold"),
                     bg="#0d1117",fg="#58d6d6").grid(row=0,column=0,sticky="w",pady=(0,4))
            self.cam_main=tk.Label(left,bg="#0b0b13",text="Waiting for student login…",
                                    fg="#3a3a5a",font=("Helvetica",11))
            self.cam_main.grid(row=1,column=0,sticky="nsew")
            left.columnconfigure(0,weight=1)
        else:
            # Interview: two cameras side by side
            tk.Label(left,text="📷  Live Cameras",font=("Helvetica",10,"bold"),
                     bg="#0d1117",fg="#ffd93d").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,4))
            left.columnconfigure(0,weight=1); left.columnconfigure(1,weight=1)
            sc_lbl=tk.Label(left,bg="#0b0b13",text="Student Camera",fg="#3a3a5a",font=("Helvetica",9))
            sc_lbl.grid(row=1,column=0,sticky="nsew",padx=(0,3))
            self.cam_main=sc_lbl
            pc_lbl=tk.Label(left,bg="#0b0b13",text="Your Camera",fg="#3a3a5a",font=("Helvetica",9))
            pc_lbl.grid(row=1,column=1,sticky="nsew",padx=(3,0))
            self.cam_pro2=pc_lbl

        # Stats strip
        sf=tk.Frame(left,bg="#0f1520",height=36); sf.grid(row=2,column=0,sticky="ew",pady=(4,0),columnspan=2)
        sf.pack_propagate(False)
        self.lbl_faces=tk.Label(sf,text="Faces: —",font=("Helvetica",9,"bold"),bg="#0f1520",fg="#0be881")
        self.lbl_faces.pack(side="left",padx=10)
        self.lbl_gaze=tk.Label(sf,text="Gaze: —",font=("Helvetica",9,"bold"),bg="#0f1520",fg="#0be881")
        self.lbl_gaze.pack(side="left",padx=10)
        self.lbl_strikes=tk.Label(sf,text="Strikes: 0/5",font=("Helvetica",9,"bold"),bg="#0f1520",fg="#0be881")
        self.lbl_strikes.pack(side="left",padx=10)
        self.lbl_phone=tk.Label(sf,text="Phone: No",font=("Helvetica",9,"bold"),bg="#0f1520",fg="#0be881")
        self.lbl_phone.pack(side="left",padx=10)

        # RIGHT: notebook
        right=tk.Frame(main,bg="#0d1117"); right.grid(row=0,column=1,sticky="nsew")
        style=ttk.Style(); style.theme_use("clam")
        style.configure("P.TNotebook",background="#0d1117",borderwidth=0)
        style.configure("P.TNotebook.Tab",background="#21262d",foreground="#c9d1d9",
                         padding=[10,6],font=("Helvetica",8,"bold"))
        style.map("P.TNotebook.Tab",background=[("selected","#575fcf")],foreground=[("selected","#ffffff")])
        nb=ttk.Notebook(right,style="P.TNotebook"); nb.pack(fill="both",expand=True)

        vf=tk.Frame(nb,bg="#0d1117"); nb.add(vf,text="⚠ Violations")
        self._build_violations(vf)

        aqf=tk.Frame(nb,bg="#0d1117"); nb.add(aqf,text="➕ Add Q")
        self._build_add_q(aqf)

        qbf=tk.Frame(nb,bg="#0d1117"); nb.add(qbf,text="📋 Bank")
        self._build_qbank(qbf)

        rf=tk.Frame(nb,bg="#0d1117"); nb.add(rf,text="📊 Results")
        self._build_results(rf)

        if self.mode=="interview":
            nf=tk.Frame(nb,bg="#0d1117"); nb.add(nf,text="📝 Notes")
            self._build_notes(nf)

    # ── Violations poll ────────────────────────────────────────────────────
    def _build_violations(self, p):
        tk.Label(p,text="Real-time Violation Log",font=("Helvetica",10,"bold"),
                 bg="#0d1117",fg="#ff6b9d").pack(anchor="w",padx=8,pady=(8,4))
        scr=tk.Scrollbar(p); scr.pack(side="right",fill="y")
        self.vlog=tk.Text(p,font=("Courier",8),bg="#060610",fg="#c9d1d9",
                           bd=0,relief="flat",wrap="word",yscrollcommand=scr.set,state="disabled")
        self.vlog.pack(fill="both",expand=True,padx=8,pady=(0,4))
        scr.configure(command=self.vlog.yview)
        # Configure all tags once here — not on every poll
        self.vlog.tag_configure("strike",  foreground="#ff4444", font=("Courier",8,"bold"))
        self.vlog.tag_configure("warn",    foreground="#ffaa00")
        self.vlog.tag_configure("blocked", foreground="#ff8c00")
        self.vlog.tag_configure("keystroke",foreground="#7090ff")
        self.vlog.tag_configure("appwarn", foreground="#c8a000")
        self.vlog.tag_configure("ok",      foreground="#0be881")
        self.vlog.tag_configure("info",    foreground="#8b949e")
        tk.Button(p,text="Clear Log",font=("Helvetica",8),bg="#21262d",fg="#8b949e",
            bd=0,relief="flat",cursor="hand2",
            command=self._clear_log).pack(pady=(0,6))

    def _clear_log(self):
        try:
            self.vlog.configure(state="normal")
            self.vlog.delete("1.0","end")
            self.vlog.configure(state="disabled")
        except Exception: pass

    def _poll_violations(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return

        hub = _hub if self.mode=="exam" else _iv_hub
        if hub:
            try:
                viols = list(hub.violations)   # snapshot under lock
                self.vlog.configure(state="normal")
                self.vlog.delete("1.0", "end")
                for v in viols:
                    vu = v.upper()
                    if   "STRIKE" in vu:          tag = "strike"
                    elif "TERMINATED" in vu:      tag = "strike"
                    elif "WARNING" in vu:         tag = "warn"
                    elif "BLOCKED_APP" in vu:     tag = "blocked"
                    elif "TAB_SWITCH" in vu:      tag = "blocked"
                    elif "KEYSTROKE" in vu:       tag = "keystroke"
                    elif "APP_WARNING" in vu:     tag = "appwarn"
                    elif "START" in vu:           tag = "ok"
                    else:                         tag = "info"
                    self.vlog.insert("end", v + "\n", tag)
                self.vlog.configure(state="disabled")
                self.vlog.see("end")
            except Exception as e:
                print(f"[ViolationPoll] {e}")

        self.root.after(800, self._poll_violations)

    # ── Add Question ──────────────────────────────────────────────────────
    def _build_add_q(self, parent):
        tk.Label(parent,text="Add New Question",font=("Helvetica",10,"bold"),
                 bg="#0d1117",fg="#0be881").pack(anchor="w",padx=10,pady=(10,4))
        canvas=tk.Canvas(parent,bg="#0d1117",highlightthickness=0)
        scr=tk.Scrollbar(parent,command=canvas.yview)
        canvas.configure(yscrollcommand=scr.set)
        scr.pack(side="right",fill="y"); canvas.pack(fill="both",expand=True)
        inner=tk.Frame(canvas,bg="#0d1117"); canvas.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        self._aq={}

        def lbl(txt):
            tk.Label(inner,text=txt,font=("Helvetica",9,"bold"),
                     bg="#0d1117",fg="#c9d1d9",anchor="w").pack(fill="x",padx=10,pady=(8,0))

        lbl("Question *")
        self._aq["q"]=tk.Text(inner,font=("Helvetica",10),bg="#161b22",fg="#f0f6fc",
                               insertbackground="#f0f6fc",bd=0,relief="flat",height=3)
        self._aq["q"].pack(fill="x",padx=10,pady=(2,0),ipady=4)

        for key,label in [("a","Option A *"),("b","Option B *"),("c","Option C *"),("d","Option D *")]:
            lbl(label)
            self._aq[key]=tk.Entry(inner,font=("Helvetica",10),bg="#161b22",fg="#f0f6fc",
                                    insertbackground="#f0f6fc",bd=0,relief="flat")
            self._aq[key].pack(fill="x",padx=10,pady=(2,0),ipady=6)

        lbl("Correct Answer")
        self._aq_ans=tk.StringVar(value="A")
        af=tk.Frame(inner,bg="#0d1117"); af.pack(padx=10,anchor="w",pady=(2,0))
        for opt in ["A","B","C","D"]:
            tk.Radiobutton(af,text=opt,variable=self._aq_ans,value=opt,
                font=("Helvetica",10,"bold"),bg="#0d1117",fg="#0be881",
                selectcolor="#0d3b2e",activebackground="#0d1117").pack(side="left",padx=8)

        row2=tk.Frame(inner,bg="#0d1117"); row2.pack(fill="x",padx=10,pady=(8,0))
        tk.Label(row2,text="Marks",font=("Helvetica",9,"bold"),bg="#0d1117",fg="#c9d1d9").pack(side="left")
        self._aq["marks"]=tk.Entry(row2,font=("Helvetica",10),width=5,bg="#161b22",fg="#f0f6fc",
                                    insertbackground="#f0f6fc",bd=0,relief="flat")
        self._aq["marks"].insert(0,"1"); self._aq["marks"].pack(side="left",padx=(4,16),ipady=5)
        tk.Label(row2,text="Category",font=("Helvetica",9,"bold"),bg="#0d1117",fg="#c9d1d9").pack(side="left")
        self._aq["cat"]=tk.Entry(row2,font=("Helvetica",10),width=12,bg="#161b22",fg="#f0f6fc",
                                  insertbackground="#f0f6fc",bd=0,relief="flat")
        self._aq["cat"].insert(0,"General"); self._aq["cat"].pack(side="left",padx=(4,0),ipady=5)

        tk.Button(inner,text="💾  Save Question",font=("Helvetica",10,"bold"),
            bg="#0be881",fg="#0d1117",bd=0,relief="flat",cursor="hand2",
            command=self._save_q).pack(fill="x",padx=10,pady=14,ipady=8)

    def _save_q(self):
        q=self._aq["q"].get("1.0","end").strip()
        a=self._aq["a"].get().strip(); b=self._aq["b"].get().strip()
        c=self._aq["c"].get().strip(); d=self._aq["d"].get().strip()
        ans=self._aq_ans.get()
        cat=self._aq["cat"].get().strip() or "General"
        try: marks=int(self._aq["marks"].get())
        except: marks=1
        if not all([q,a,b,c,d]): messagebox.showerror("Error","Fill all required fields"); return
        db_add_question(q,a,b,c,d,ans,marks,cat)
        messagebox.showinfo("Saved","Question added ✓")
        self._aq["q"].delete("1.0","end")
        for k in ["a","b","c","d"]: self._aq[k].delete(0,"end")
        self._aq["marks"].delete(0,"end"); self._aq["marks"].insert(0,"1")
        self._aq["cat"].delete(0,"end");   self._aq["cat"].insert(0,"General")
        self._refresh_qbank()

    # ── Question Bank ─────────────────────────────────────────────────────
    def _build_qbank(self, parent):
        top=tk.Frame(parent,bg="#0d1117"); top.pack(fill="x",padx=8,pady=(8,4))
        tk.Label(top,text="Question Bank",font=("Helvetica",10,"bold"),
                 bg="#0d1117",fg="#ffd93d").pack(side="left")
        tk.Button(top,text="↺",font=("Helvetica",10),bg="#21262d",fg="#8b949e",
            bd=0,relief="flat",cursor="hand2",command=self._refresh_qbank).pack(side="right",ipady=2,padx=4)
        self._qb_canvas=tk.Canvas(parent,bg="#0d1117",highlightthickness=0)
        scr=tk.Scrollbar(parent,command=self._qb_canvas.yview)
        self._qb_canvas.configure(yscrollcommand=scr.set)
        scr.pack(side="right",fill="y"); self._qb_canvas.pack(fill="both",expand=True,padx=4)
        self._qb_inner=tk.Frame(self._qb_canvas,bg="#0d1117")
        self._qb_canvas.create_window((0,0),window=self._qb_inner,anchor="nw")
        self._qb_inner.bind("<Configure>",
            lambda e:self._qb_canvas.configure(scrollregion=self._qb_canvas.bbox("all")))
        self._refresh_qbank()

    def _refresh_qbank(self):
        for w in self._qb_inner.winfo_children(): w.destroy()
        qs=db_get_questions()
        if not qs:
            tk.Label(self._qb_inner,text="No questions.",font=("Helvetica",9),
                     bg="#0d1117",fg="#8b949e").pack(padx=10,pady=10); return
        for q in qs:
            card=tk.Frame(self._qb_inner,bg="#161b22"); card.pack(fill="x",padx=4,pady=3)
            txt=q[1][:60]+"…" if len(q[1])>60 else q[1]
            cat=q[8] if len(q)>8 else "—"
            tk.Label(card,text=f"Q{q[0]}: {txt}",font=("Helvetica",9),bg="#161b22",fg="#c9d1d9",
                     anchor="w",wraplength=200,justify="left").pack(side="left",padx=8,pady=6,fill="x",expand=True)
            info=tk.Frame(card,bg="#161b22"); info.pack(side="left")
            tk.Label(info,text=f"Ans:{q[6]}",font=("Helvetica",8,"bold"),bg="#161b22",fg="#0be881").pack(anchor="e")
            tk.Label(info,text=f"{q[7]}mk {cat}",font=("Helvetica",7),bg="#161b22",fg="#575fcf").pack(anchor="e")
            tk.Button(card,text="✏",font=("Helvetica",10),bg="#161b22",fg="#ffd93d",
                bd=0,relief="flat",cursor="hand2",
                command=lambda row=q:self._edit_q(row)).pack(side="right",padx=2)
            tk.Button(card,text="🗑",font=("Helvetica",10),bg="#161b22",fg="#ff6b9d",
                bd=0,relief="flat",cursor="hand2",
                command=lambda qid=q[0]:self._del_q(qid)).pack(side="right",padx=2)

    def _del_q(self, qid):
        if messagebox.askyesno("Delete",f"Delete Q{qid}?"):
            db_delete_question(qid); self._refresh_qbank()

    def _edit_q(self, row):
        win=tk.Toplevel(self.root); win.title(f"Edit Q{row[0]}")
        win.geometry("500x480"); win.configure(bg="#0d1117"); win.grab_set()
        fields={}
        canvas=tk.Canvas(win,bg="#0d1117",highlightthickness=0)
        scr=tk.Scrollbar(win,command=canvas.yview)
        canvas.configure(yscrollcommand=scr.set)
        scr.pack(side="right",fill="y"); canvas.pack(fill="both",expand=True)
        inner=tk.Frame(canvas,bg="#0d1117"); canvas.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))

        def lbl(txt):
            tk.Label(inner,text=txt,font=("Helvetica",9,"bold"),
                     bg="#0d1117",fg="#c9d1d9",anchor="w").pack(fill="x",padx=16,pady=(6,0))

        lbl("Question")
        fields["q"]=tk.Text(inner,font=("Helvetica",10),bg="#161b22",fg="#f0f6fc",
                             insertbackground="#f0f6fc",bd=0,relief="flat",height=3)
        fields["q"].insert("1.0",row[1]); fields["q"].pack(fill="x",padx=16,pady=(2,0),ipady=4)
        for i,(key,label) in enumerate([("a","Option A"),("b","Option B"),("c","Option C"),("d","Option D")]):
            lbl(label)
            fields[key]=tk.Entry(inner,font=("Helvetica",10),bg="#161b22",fg="#f0f6fc",
                                  insertbackground="#f0f6fc",bd=0,relief="flat")
            fields[key].insert(0,row[2+i]); fields[key].pack(fill="x",padx=16,pady=(2,0),ipady=6)
        lbl("Correct Answer")
        ans_var=tk.StringVar(value=row[6])
        af=tk.Frame(inner,bg="#0d1117"); af.pack(padx=16,anchor="w")
        for opt in ["A","B","C","D"]:
            tk.Radiobutton(af,text=opt,variable=ans_var,value=opt,
                font=("Helvetica",10,"bold"),bg="#0d1117",fg="#0be881",
                selectcolor="#0d3b2e",activebackground="#0d1117").pack(side="left",padx=6)
        row2=tk.Frame(inner,bg="#0d1117"); row2.pack(fill="x",padx=16,pady=(6,0))
        tk.Label(row2,text="Marks",font=("Helvetica",9,"bold"),bg="#0d1117",fg="#c9d1d9").pack(side="left")
        fields["marks"]=tk.Entry(row2,font=("Helvetica",10),width=5,bg="#161b22",fg="#f0f6fc",
                                  insertbackground="#f0f6fc",bd=0,relief="flat")
        fields["marks"].insert(0,str(row[7]) if len(row)>7 else "1")
        fields["marks"].pack(side="left",padx=(4,16),ipady=5)
        tk.Label(row2,text="Category",font=("Helvetica",9,"bold"),bg="#0d1117",fg="#c9d1d9").pack(side="left")
        fields["cat"]=tk.Entry(row2,font=("Helvetica",10),width=12,bg="#161b22",fg="#f0f6fc",
                                insertbackground="#f0f6fc",bd=0,relief="flat")
        fields["cat"].insert(0,row[8] if len(row)>8 else "General")
        fields["cat"].pack(side="left",padx=(4,0),ipady=5)

        def save():
            q=fields["q"].get("1.0","end").strip()
            a=fields["a"].get().strip(); b=fields["b"].get().strip()
            c=fields["c"].get().strip(); d=fields["d"].get().strip()
            ans=ans_var.get(); cat=fields["cat"].get().strip() or "General"
            try: marks=int(fields["marks"].get())
            except: marks=1
            if not all([q,a,b,c,d]): messagebox.showerror("Error","Fill all fields"); return
            db_update_question(row[0],q,a,b,c,d,ans,marks,cat)
            messagebox.showinfo("Updated","Question updated ✓")
            win.destroy(); self._refresh_qbank()

        tk.Button(inner,text="💾  Update",font=("Helvetica",10,"bold"),bg="#575fcf",fg="#fff",
            bd=0,relief="flat",cursor="hand2",command=save).pack(fill="x",padx=16,pady=14,ipady=8)

    # ── Results ───────────────────────────────────────────────────────────
    def _build_results(self, parent):
        top=tk.Frame(parent,bg="#0d1117"); top.pack(fill="x",padx=8,pady=(8,4))
        tk.Label(top,text="Exam Results & Logs",font=("Helvetica",10,"bold"),
                 bg="#0d1117",fg="#575fcf").pack(side="left")
        tk.Button(top,text="↺",font=("Helvetica",10),bg="#21262d",fg="#8b949e",
            bd=0,relief="flat",cursor="hand2",command=self._refresh_results).pack(side="right",ipady=2,padx=4)
        self._res_frame=tk.Frame(parent,bg="#0d1117"); self._res_frame.pack(fill="both",expand=True,padx=4)
        self._refresh_results()

    def _refresh_results(self):
        for w in self._res_frame.winfo_children(): w.destroy()
        files=[f for f in os.listdir('.') if f.endswith('_result.csv') or f.endswith('_exam_log.csv')]
        if not files:
            tk.Label(self._res_frame,text="No result files yet.",font=("Helvetica",9),
                     bg="#0d1117",fg="#8b949e").pack(padx=10,pady=10); return
        canvas=tk.Canvas(self._res_frame,bg="#0d1117",highlightthickness=0)
        scr=tk.Scrollbar(self._res_frame,command=canvas.yview)
        canvas.configure(yscrollcommand=scr.set)
        scr.pack(side="right",fill="y"); canvas.pack(fill="both",expand=True)
        inner=tk.Frame(canvas,bg="#0d1117"); canvas.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        for fname in sorted(files):
            row=tk.Frame(inner,bg="#161b22"); row.pack(fill="x",padx=4,pady=3)
            tk.Label(row,text=fname,font=("Courier",9),bg="#161b22",fg="#c9d1d9",
                     anchor="w").pack(side="left",padx=8,pady=6,fill="x",expand=True)
            tk.Button(row,text="View",font=("Helvetica",8,"bold"),bg="#575fcf",fg="#fff",
                bd=0,relief="flat",cursor="hand2",
                command=lambda f=fname:self._view_file(f)).pack(side="right",padx=6,pady=4,ipady=2)

    def _view_file(self, fname):
        try:
            with open(fname,encoding='utf-8') as f: content=f.read()
        except: content="Could not read file."
        win=tk.Toplevel(self.root); win.title(fname); win.geometry("640x420"); win.configure(bg="#0d1117")
        scr=tk.Scrollbar(win); scr.pack(side="right",fill="y")
        txt=tk.Text(win,font=("Courier",9),bg="#0b0b13",fg="#c9d1d9",bd=0,wrap="none",yscrollcommand=scr.set)
        txt.pack(fill="both",expand=True,padx=8,pady=8)
        txt.insert("end",content); txt.configure(state="disabled"); scr.configure(command=txt.yview)

    # ── Interview Notes (proctor types, student sees) ─────────────────────
    def _build_notes(self, parent):
        tk.Label(parent,text="Interview Notes (sent to student)",
                 font=("Helvetica",10,"bold"),bg="#0d1117",fg="#ffd93d").pack(anchor="w",padx=8,pady=(8,4))
        self._notes_box=tk.Text(parent,font=("Helvetica",10),bg="#161b22",fg="#f0f6fc",
                                 insertbackground="#f0f6fc",bd=0,relief="flat",wrap="word")
        self._notes_box.pack(fill="both",expand=True,padx=8,pady=(0,4))
        tk.Button(parent,text="📤 Push Notes to Student",font=("Helvetica",10,"bold"),
            bg="#ffd93d",fg="#0d1117",bd=0,relief="flat",cursor="hand2",
            command=self._push_notes).pack(fill="x",padx=8,pady=(0,8),ipady=7)

    def _push_notes(self):
        if not hasattr(self,'_notes_box'): return
        content=self._notes_box.get("1.0","end").strip()
        # Write to a shared file that the student window reads
        try:
            with open("interview_notes.txt","w",encoding="utf-8") as f: f.write(content)
            messagebox.showinfo("Sent","Notes pushed to student ✓")
        except Exception as e:
            messagebox.showerror("Error",str(e))

    # ── Camera poll ────────────────────────────────────────────────────────
    def _poll_cam(self):
        try:
            if not self.root.winfo_exists(): return
        except Exception: return

        hub = _hub if self.mode=="exam" else _iv_hub

        if hub:
            try:
                if self.mode=="exam":
                    frame = hub.get_frame()
                    if frame is not None:
                        self._show_frame(self.cam_main, frame)
                    else:
                        self.cam_main.configure(
                            text="Camera starting…", fg="#575fcf", image="")
                    fc = hub.face_count
                    gd = hub.gaze_dir
                    sc = hub.strike_count
                    ph = getattr(hub, 'phone_detected', False)
                else:
                    sf = hub.get_student_frame()
                    if sf is not None:
                        self._show_frame(self.cam_main, sf)
                    pf = hub.get_proctor_frame()
                    if pf is not None and hasattr(self, 'cam_pro2'):
                        self._show_frame(self.cam_pro2, pf)
                    fc = hub.face_count
                    gd = hub.gaze_dir
                    sc = hub.strike_count
                    ph = False

                fc_col  = "#0be881" if fc == 1 else "#ff4444" if fc == 0 else "#ffaa00"
                gd_col  = "#0be881" if gd == "center" else "#ffaa00"
                sc_col  = "#0be881" if sc == 0 else "#ffaa00" if sc < 3 else "#ff4444"
                ph_col  = "#ff4444" if ph else "#0be881"
                self.lbl_faces.configure(text=f"Faces: {fc}", fg=fc_col)
                self.lbl_gaze.configure(text=f"Gaze: {gd}", fg=gd_col)
                self.lbl_strikes.configure(
                    text=f"Strikes: {sc}/{CameraHub.MAX_STRIKES}", fg=sc_col)
                self.lbl_phone.configure(
                    text=f"Phone: {'⚠ YES' if ph else 'No'}", fg=ph_col)

            except Exception as e:
                print(f"[ProctorCam] Error: {e}")
        else:
            try:
                self.cam_main.configure(
                    text="Waiting for student to log in…", fg="#3a3a5a", image="")
            except Exception:
                pass

        self.root.after(100, self._poll_cam)

    def _show_frame(self, label, frame):
        try:
            lw = max(label.winfo_width(),  320)
            lh = max(label.winfo_height(), 240)
            h, w = frame.shape[:2]
            if h == 0 or w == 0:
                return
            scale = min(lw / w, lh / h)
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            resized = cv2.resize(frame, (nw, nh))
            rgb     = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            img     = ImageTk.PhotoImage(Image.fromarray(rgb))
            label.configure(image=img, text="")
            label.image = img          # keep hard reference — MUST or GC kills it
        except Exception as e:
            print(f"[_show_frame] {e}")

    # ── Violations poll ────────────────────────────────────────────────────
    def _toggle(self):
        self.is_dark=not self.is_dark; self.theme=DARK if self.is_dark else LIGHT
        t=self.theme
        self.btn_tog.configure(text=f"{t['mode_icon']}  {t['mode_text']}",
                                bg=t["btn_toggle_bg"],fg=t["btn_toggle_fg"])

    def _logout(self):
        if _hub: _hub.stop()
        if _iv_hub: _iv_hub.stop()
        self.root.destroy(); MainLogin().run()

    def _close(self):
        if _hub: _hub.stop()
        if _iv_hub: _iv_hub.stop()
        self.root.destroy()

    def run(self): self.root.mainloop()

# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  NETWORK SERVER  (runs on student's machine, proctor connects from other PC)
#  Endpoints:
#    GET /frame       → latest JPEG camera frame
#    GET /stats       → JSON: face_count, gaze_dir, strike_count, phone
#    GET /violations  → JSON: list of violation strings
#    GET /ping        → {"status":"ok","student":"<id>"}
# ══════════════════════════════════════════════════════════════════════════════
_net_server = None

def start_network_server(port=6000):
    """Start a tiny HTTP server in a daemon thread so proctor can connect remotely."""
    try:
        from flask import Flask, jsonify, Response, request
    except ImportError:
        print("[⚠] flask not installed — remote proctor disabled. Run: pip install flask")
        return

    app = Flask("ExamShieldServer")

    # Silence Flask request logs
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    @app.route("/ping")
    def ping():
        sid = (_hub.student_id if _hub else
               _iv_hub.student_id if _iv_hub else "none")
        mode = "interview" if _iv_hub else "exam"
        return jsonify(status="ok", student=sid, mode=mode)

    @app.route("/frame")
    def frame():
        hub = _hub or _iv_hub
        if hub is None:
            return Response("no session", status=204)
        f = (hub.get_frame() if hasattr(hub, 'get_frame')
             else hub.get_student_frame())
        if f is None:
            return Response("no frame", status=204)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return Response("encode error", status=500)
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/push_proctor_frame", methods=["POST"])
    def push_proctor_frame():
        """Proctor's machine pushes its webcam frame here as JPEG bytes."""
        if _iv_hub is None:
            return jsonify(ok=False, reason="no interview session"), 204
        data = request.get_data()
        if not data:
            return jsonify(ok=False, reason="no data"), 400
        arr   = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify(ok=False, reason="decode failed"), 400
        # Write into InterviewHub's proctor_frame buffer
        with _iv_hub._lock:
            _iv_hub.proctor_frame = frame
        return jsonify(ok=True)

    @app.route("/stats")
    def stats():
        hub = _hub or _iv_hub
        if hub is None:
            return jsonify(active=False)
        return jsonify(
            active       = True,
            student_id   = hub.student_id,
            face_count   = hub.face_count,
            gaze_dir     = hub.gaze_dir,
            strike_count = hub.strike_count,
            phone        = getattr(hub, 'phone_detected', False),
            terminated   = hub.terminated,
            max_strikes  = CameraHub.MAX_STRIKES,
            mode         = "interview" if _iv_hub else "exam",
        )

    @app.route("/violations")
    def violations():
        hub = _hub or _iv_hub
        if hub is None:
            return jsonify(violations=[])
        return jsonify(violations=list(hub.violations))

    def _run():
        app.run(host="0.0.0.0", port=port, threaded=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Print IP so student can share it with proctor
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"

    print(f"\n{'═'*55}")
    print(f"  🌐 Remote Proctor Server started on port {port}")
    print(f"  📡 Share this address with the proctor:")
    print(f"     http://{ip}:{port}")
    print(f"  Proctor runs:  python proctor_client.py {ip}")
    print(f"{'═'*55}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    try:
        from face_auth import init_face_db
        init_face_db()
    except ImportError:
        pass

    # Print dependency warnings for optional packages
    if not _KEYBOARD_HOOK_AVAILABLE:
        print("[⚠] 'keyboard' not installed — keystroke blocking disabled")
        print("    Fix: pip install keyboard")
    if not _PSUTIL_AVAILABLE:
        print("[⚠] 'psutil' not installed — app blocking disabled")
        print("    Fix: pip install psutil")
    try:
        import win32gui
    except ImportError:
        print("[⚠] 'pywin32' not installed — tab-switch detection via win32 disabled")
        print("    Fix: pip install pywin32")

    # Start network server so proctor can connect from another machine
    start_network_server(port=6000)

    MainLogin().run()