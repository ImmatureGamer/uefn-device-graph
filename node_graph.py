import unreal
import tkinter as tk
from tkinter import filedialog
import os
import re
import math
import subprocess
import json

# ============================================================
# UEFN DEVICE NODE GRAPH v3 - FULL FEATURED
# Broken connection detection, orphan warnings, search,
# zoom, export, VS Code integration, annotations,
# device type filtering, re-scan with position memory
# ============================================================

DEVICE_COLORS = {
    "verse": "#e94560", "elimination": "#ff6b35", "spawner": "#27ae60",
    "guard": "#27ae60", "hud": "#2980b9", "round": "#8e44ad",
    "item": "#f39c12", "settings": "#16a085", "timer": "#e67e22",
    "trigger": "#d35400", "score": "#2980b9", "audio": "#1abc9c",
    "teleport": "#9b59b6", "message": "#2980b9", "generic": "#5d6d7e",
}
EDGE_COLORS = {"editable": "#e94560", "event": "#2ecc71", "function": "#3498db"}
WARN_COLOR = "#f1c40f"
ERROR_COLOR = "#e74c3c"

def classify_device(cn, lb):
    t = (cn + " " + lb).lower()
    for k in DEVICE_COLORS:
        if k in t: return k
    return "generic"

# ---- LEVEL SCANNER ----
def scan_level():
    devs = []
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    for a in actors:
        cn = a.get_class().get_name()
        if any(k in cn for k in ["Device", "device", "CRD", "VerseDevice", "Settings"]):
            label = ""
            try: label = a.get_actor_label()
            except: pass
            loc = a.get_actor_location()
            devs.append({"label": label or cn, "class": cn, "loc": (loc.x, loc.y, loc.z), "actor": a})
    return devs

# ---- VERSE PARSER ----
def find_verse_files(path):
    files = []
    if not os.path.exists(path): return files
    for root, dirs, fnames in os.walk(path):
        for f in fnames:
            if f.endswith(".verse") and "digest" not in f.lower():
                files.append(os.path.join(root, f))
    return files

def parse_verse(filepath):
    r = {"file": os.path.basename(filepath), "filepath": filepath, "device": "",
         "editables": [], "events": [], "calls": [], "functions": [], "modules": []}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except: return r

    m = re.search(r'(\w+)\s*:=\s*class\s*\(\s*creative_device\s*\)', content)
    if m: r["device"] = m.group(1)

    for m in re.finditer(r'using\s*\{\s*(.+?)\s*\}', content):
        r["modules"].append(m.group(1))

    for m in re.finditer(r'@editable\s+(\w+)\s*:\s*([\w\[\]<>?]+)', content):
        r["editables"].append({"name": m.group(1), "type": m.group(2)})

    for m in re.finditer(r'(\w+)\.(\w+)\s*\.\s*Subscribe\s*\(\s*(\w+)\s*\)', content):
        r["events"].append({"source": m.group(1), "event": m.group(2), "handler": m.group(3)})

    enames = [e["name"] for e in r["editables"]]
    for en in enames:
        for m in re.finditer(rf'{en}\s*\.\s*(\w+)\s*[\(\[]', content):
            fn = m.group(1)
            if fn not in ["Subscribe", "Unsubscribe"]:
                r["calls"].append({"target": en, "func": fn})

    # Parse function definitions (OnBegin, OnEnd, custom)
    for m in re.finditer(r'(\w+)\s*(?:<\w+>)?\s*\([^)]*\)\s*(?:<\w+>)?\s*:\s*void\s*=', content):
        fname = m.group(1)
        r["functions"].append(fname)

    # Find which functions are actually called
    r["called_functions"] = set()
    for m in re.finditer(r'(?:self\.|)(\w+)\s*\(', content):
        r["called_functions"].add(m.group(1))

    return r


def build_graph(devices, verse_list, old_nodes=None):
    nodes = []
    edges = []
    warnings = []

    # Preserve old positions
    old_pos = {}
    if old_nodes:
        for n in old_nodes:
            old_pos[n["label"]] = (n["x"], n["y"])
            if n.get("note"):
                old_pos[n["label"] + "_note"] = n["note"]

    for i, dev in enumerate(devices):
        tk_key = classify_device(dev["class"], dev["label"])
        color = DEVICE_COLORS.get(tk_key, DEVICE_COLORS["generic"])
        ox, oy = old_pos.get(dev["label"], (0, 0))
        note = old_pos.get(dev["label"] + "_note", "")
        nodes.append({
            "id": f"d{i}", "label": dev["label"], "class": dev["class"],
            "color": color, "x": ox, "y": oy, "loc": dev["loc"],
            "actor": dev["actor"], "editables": [], "events": [], "calls": [],
            "functions": [], "called_functions": set(), "verse_file": "",
            "verse_path": "", "type_key": tk_key, "note": note,
            "warnings": [], "errors": [],
        })

    for vd in verse_list:
        if not vd["device"]: continue
        matched = None
        for node in nodes:
            nl = node["label"].lower().replace(" ", "").replace("_", "")
            vn = vd["device"].lower().replace("_", "")
            if vn in nl or nl in vn:
                matched = node
                break
        if matched:
            matched["editables"] = vd["editables"]
            matched["events"] = vd["events"]
            matched["calls"] = vd["calls"]
            matched["functions"] = vd["functions"]
            matched["called_functions"] = vd.get("called_functions", set())
            matched["verse_file"] = vd["file"]
            matched["verse_path"] = vd["filepath"]
        else:
            ox, oy = old_pos.get(vd["device"], (0, 0))
            note = old_pos.get(vd["device"] + "_note", "")
            nodes.append({
                "id": f"v_{vd['device']}", "label": vd["device"], "class": "VerseDevice",
                "color": DEVICE_COLORS["verse"], "x": ox, "y": oy, "loc": (0,0,0),
                "actor": None, "editables": vd["editables"], "events": vd["events"],
                "calls": vd["calls"], "functions": vd["functions"],
                "called_functions": vd.get("called_functions", set()),
                "verse_file": vd["file"], "verse_path": vd["filepath"],
                "type_key": "verse", "note": note, "warnings": [], "errors": [],
            })

    # Edges from editables
    for node in nodes:
        for ed in node.get("editables", []):
            etype = ed["type"].lower().replace("_device", "").replace("_", "")
            found = False
            for target in nodes:
                if target["id"] == node["id"]: continue
                tc = target["class"].lower().replace("_", "").replace("device", "")
                tl = target["label"].lower().replace(" ", "").replace("_", "")
                if etype in tc or etype in tl or tc in etype or tl in etype:
                    edges.append({"from": node["id"], "to": target["id"],
                                  "label": ed["name"], "type": "editable",
                                  "color": EDGE_COLORS["editable"]})
                    found = True
                    break
            if not found and "device" in ed["type"].lower():
                node["errors"].append(f"Broken: @editable {ed['name']} ({ed['type']}) not wired")
                warnings.append(f"{node['label']}: @editable {ed['name']} has no target")

    # Edges from events
    for node in nodes:
        for ev in node.get("events", []):
            src = ev["source"].lower()
            for target in nodes:
                if target["id"] == node["id"]: continue
                tl = target["label"].lower().replace(" ", "").replace("_", "")
                if src in tl or tl in src:
                    edges.append({"from": target["id"], "to": node["id"],
                                  "label": ev["event"], "type": "event",
                                  "color": EDGE_COLORS["event"]})
                    break

    # Detect orphans
    connected_ids = set()
    for e in edges:
        connected_ids.add(e["from"])
        connected_ids.add(e["to"])
    for node in nodes:
        if node["id"] not in connected_ids and node["type_key"] != "settings":
            node["warnings"].append("Orphan: no connections")
            warnings.append(f"{node['label']}: orphan device (no connections)")

    # Detect unused functions
    for node in nodes:
        for func in node.get("functions", []):
            if func in ["OnBegin", "OnEnd"]: continue
            if func not in node.get("called_functions", set()):
                node["warnings"].append(f"Unused: {func}()")

    # Detect editables with default values (likely not configured)
    for node in nodes:
        for ed in node.get("editables", []):
            if "device" in ed["type"].lower():
                has_edge = any(e["from"] == node["id"] and e["label"] == ed["name"] for e in edges)
                if not has_edge:
                    node["warnings"].append(f"Unassigned: {ed['name']}")

    # Deduplicate edges
    seen = set()
    unique = []
    for e in edges:
        k = (e["from"], e["to"], e["label"])
        if k not in seen:
            seen.add(k)
            unique.append(e)

    return nodes, unique, warnings


def layout_circle(nodes, w, h):
    # Only layout nodes at (0,0) - preserve existing positions
    unplaced = [n for n in nodes if n["x"] == 0 and n["y"] == 0]
    if not unplaced: return

    n = len(unplaced)
    if n == 0: return
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.35
    for i, node in enumerate(unplaced):
        a = (2 * math.pi * i / n) - math.pi / 2
        node["x"] = cx + r * math.cos(a) - 95
        node["y"] = cy + r * math.sin(a) - 36


# ============================================================
# MAIN APP
# ============================================================

class NodeGraphApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Device Graph v3")
        self.root.geometry("1300x850")
        self.root.configure(bg="#080812")
        self.root.attributes('-topmost', True)

        self.BG = "#080812"
        self.CBG = "#0c0c1a"
        self.PBG = "#111125"
        self.FG = "#d0d0e0"
        self.ACC = "#e94560"

        self.nodes = []
        self.edges = []
        self.warnings = []
        self.drag_node = None
        self.drag_off = (0, 0)
        self.selected = None
        self.tick_handle = None
        self.pending = None
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.hidden_types = set()
        self.search_term = ""

        self.NW = 190
        self.NH = 72

        self.build_ui()
        self.start_tick()

    def build_ui(self):
        bg = self.BG; fg = self.FG; acc = self.ACC; pbg = self.PBG

        # ---- TOP BAR ----
        top = tk.Frame(self.root, bg="#0f0f22")
        top.pack(fill="x")

        tk.Label(top, text=" DEVICE GRAPH", font=("Segoe UI", 13, "bold"),
                fg=acc, bg="#0f0f22").pack(side="left", padx=10, pady=6)

        tk.Button(top, text="SCAN", bg=acc, fg="white", font=("Segoe UI", 9, "bold"),
                  relief="flat", cursor="hand2", command=self.trigger_scan, padx=10).pack(side="left", padx=3, pady=4)

        tk.Button(top, text="Re-Scan", bg="#1a1a40", fg=fg, font=("Segoe UI", 8),
                  relief="flat", cursor="hand2", command=self.trigger_rescan).pack(side="left", padx=2, pady=4)

        tk.Button(top, text="Layout", bg="#1a1a40", fg=fg, font=("Segoe UI", 8),
                  relief="flat", cursor="hand2", command=self.force_relayout).pack(side="left", padx=2, pady=4)

        # Zoom
        tk.Button(top, text="+", bg="#1a1a40", fg=fg, font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", width=2,
                  command=lambda: self.set_zoom(0.15)).pack(side="left", padx=(10, 1), pady=4)
        tk.Button(top, text="-", bg="#1a1a40", fg=fg, font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", width=2,
                  command=lambda: self.set_zoom(-0.15)).pack(side="left", padx=1, pady=4)

        self.zoom_label = tk.Label(top, text="100%", fg="#666", bg="#0f0f22", font=("Segoe UI", 8))
        self.zoom_label.pack(side="left", padx=3)

        # Search
        tk.Label(top, text="Search:", fg="#666", bg="#0f0f22", font=("Segoe UI", 9)).pack(side="left", padx=(15, 3))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.on_search())
        se = tk.Entry(top, textvariable=self.search_var, width=15, bg="#1a1a35", fg=fg,
                insertbackground=fg, font=("Segoe UI", 9), relief="flat")
        se.pack(side="left", padx=3, pady=4)

        # Export buttons
        tk.Button(top, text="Export PNG", bg="#1a1a40", fg=fg, font=("Segoe UI", 8),
                  relief="flat", cursor="hand2", command=self.export_image).pack(side="left", padx=(10, 2), pady=4)
        tk.Button(top, text="Export TXT", bg="#1a1a40", fg=fg, font=("Segoe UI", 8),
                  relief="flat", cursor="hand2", command=self.export_text).pack(side="left", padx=2, pady=4)

        # Path
        tk.Label(top, text="Verse:", fg="#444", bg="#0f0f22", font=("Segoe UI", 8)).pack(side="left", padx=(10, 2))
        self.path_var = tk.StringVar(value=r"C:\Users\Matthew\Documents\Fortnite Projects\pythonTEST\Content")
        tk.Entry(top, textvariable=self.path_var, width=30, bg="#1a1a35", fg=fg,
                insertbackground=fg, font=("Segoe UI", 8), relief="flat").pack(side="left", padx=2, pady=4)

        self.status_var = tk.StringVar(value="Click SCAN to start")
        tk.Label(top, textvariable=self.status_var, fg="#555", bg="#0f0f22",
                font=("Segoe UI", 8)).pack(side="right", padx=10)

        # ---- FILTER BAR ----
        fbar = tk.Frame(self.root, bg="#0a0a18")
        fbar.pack(fill="x")
        tk.Label(fbar, text="Show:", fg="#666", bg="#0a0a18", font=("Segoe UI", 8)).pack(side="left", padx=10)

        self.filter_vars = {}
        for key in ["verse", "elimination", "spawner", "hud", "round", "item", "settings", "generic"]:
            v = tk.BooleanVar(value=True)
            self.filter_vars[key] = v
            cb = tk.Checkbutton(fbar, text=key.capitalize(), variable=v,
                               fg=DEVICE_COLORS.get(key, "#888"), bg="#0a0a18",
                               selectcolor="#1a1a30", font=("Segoe UI", 8),
                               activebackground="#0a0a18", command=self.on_filter)
            cb.pack(side="left", padx=3)

        # Warnings count
        self.warn_label = tk.Label(fbar, text="", fg=WARN_COLOR, bg="#0a0a18",
                                    font=("Segoe UI", 8, "bold"))
        self.warn_label.pack(side="right", padx=10)

        # ---- MAIN AREA ----
        main = tk.Frame(self.root, bg=bg)
        main.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(main, bg=self.CBG, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<MouseWheel>", self.on_scroll)

        # ---- RIGHT PANEL ----
        panel = tk.Frame(main, bg=pbg, width=300)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        # Scrollable panel
        pcanvas = tk.Canvas(panel, bg=pbg, highlightthickness=0, bd=0)
        psb = tk.Scrollbar(panel, orient="vertical", command=pcanvas.yview)
        self.pframe = tk.Frame(pcanvas, bg=pbg)

        self.pframe.bind("<Configure>", lambda e: pcanvas.configure(scrollregion=pcanvas.bbox("all")))
        pcanvas.create_window((0, 0), window=self.pframe, anchor="nw", width=295)
        pcanvas.configure(yscrollcommand=psb.set)
        psb.pack(side="right", fill="y")
        pcanvas.pack(side="left", fill="both", expand=True)

        pf = self.pframe

        # Device info
        tk.Label(pf, text="DEVICE INFO", font=("Segoe UI", 11, "bold"),
                fg=acc, bg=pbg).pack(pady=(12, 5), padx=12, anchor="w")

        self.info_name = tk.Label(pf, text="No device selected", fg="white",
                                   bg=pbg, font=("Segoe UI", 11, "bold"), wraplength=265, justify="left")
        self.info_name.pack(padx=12, anchor="w")

        self.info_class = tk.Label(pf, text="", fg="#888", bg=pbg, font=("Segoe UI", 9), wraplength=265)
        self.info_class.pack(padx=12, anchor="w")

        self.info_loc = tk.Label(pf, text="", fg="#555", bg=pbg, font=("Segoe UI", 8))
        self.info_loc.pack(padx=12, anchor="w", pady=(0, 3))

        # Action buttons
        abf = tk.Frame(pf, bg=pbg)
        abf.pack(fill="x", padx=12, pady=3)

        self.focus_btn = tk.Button(abf, text="Select + Focus (F)", bg="#1a1a40", fg=self.FG,
                                    font=("Segoe UI", 8, "bold"), relief="flat", cursor="hand2",
                                    command=self.focus_selected)
        self.focus_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self.vscode_btn = tk.Button(abf, text="Open in VS Code", bg="#1a1a40", fg=self.FG,
                                     font=("Segoe UI", 8, "bold"), relief="flat", cursor="hand2",
                                     command=self.open_vscode)
        self.vscode_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))

        tk.Frame(pf, bg="#2a2a45", height=1).pack(fill="x", padx=12, pady=6)

        # Warnings/Errors
        tk.Label(pf, text="WARNINGS", font=("Segoe UI", 9, "bold"), fg=WARN_COLOR, bg=pbg).pack(padx=12, anchor="w")
        self.warn_text = tk.Text(pf, bg="#0a0a1a", fg=WARN_COLOR, font=("Consolas", 8),
                                  height=3, relief="flat", bd=0, padx=6, pady=4)
        self.warn_text.pack(fill="x", padx=12)

        # Editables
        tk.Label(pf, text="@editable", font=("Segoe UI", 9, "bold"),
                fg=EDGE_COLORS["editable"], bg=pbg).pack(padx=12, anchor="w", pady=(6, 0))
        self.edit_text = tk.Text(pf, bg="#0a0a1a", fg="#ccc", font=("Consolas", 8),
                                  height=4, relief="flat", bd=0, padx=6, pady=4)
        self.edit_text.pack(fill="x", padx=12)

        # Events
        tk.Label(pf, text="Events", font=("Segoe UI", 9, "bold"),
                fg=EDGE_COLORS["event"], bg=pbg).pack(padx=12, anchor="w", pady=(6, 0))
        self.event_text = tk.Text(pf, bg="#0a0a1a", fg="#ccc", font=("Consolas", 8),
                                   height=4, relief="flat", bd=0, padx=6, pady=4)
        self.event_text.pack(fill="x", padx=12)

        # Functions
        tk.Label(pf, text="Functions", font=("Segoe UI", 9, "bold"),
                fg=EDGE_COLORS["function"], bg=pbg).pack(padx=12, anchor="w", pady=(6, 0))
        self.func_text = tk.Text(pf, bg="#0a0a1a", fg="#ccc", font=("Consolas", 8),
                                  height=4, relief="flat", bd=0, padx=6, pady=4)
        self.func_text.pack(fill="x", padx=12)

        # Note / Annotation
        tk.Frame(pf, bg="#2a2a45", height=1).pack(fill="x", padx=12, pady=6)
        tk.Label(pf, text="NOTES", font=("Segoe UI", 9, "bold"), fg="#888", bg=pbg).pack(padx=12, anchor="w")
        self.note_text = tk.Text(pf, bg="#0a0a1a", fg="#ccc", font=("Segoe UI", 9),
                                  height=3, relief="flat", bd=0, padx=6, pady=4)
        self.note_text.pack(fill="x", padx=12)
        self.note_text.bind("<KeyRelease>", self.on_note_change)

        # Verse file
        self.verse_label = tk.Label(pf, text="", fg="#e94560", bg=pbg, font=("Segoe UI", 8))
        self.verse_label.pack(padx=12, anchor="w", pady=(6, 0))

        # Legend
        tk.Frame(pf, bg="#2a2a45", height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(pf, text="CONNECTIONS", font=("Segoe UI", 9, "bold"), fg="#666", bg=pbg).pack(padx=12, anchor="w")
        for label, color, dashed in [
            ("@editable ref", EDGE_COLORS["editable"], False),
            ("Event sub", EDGE_COLORS["event"], True),
        ]:
            lr = tk.Frame(pf, bg=pbg)
            lr.pack(fill="x", padx=12, pady=1)
            c = tk.Canvas(lr, width=20, height=3, bg=pbg, highlightthickness=0)
            c.pack(side="left", padx=(0, 4))
            if dashed:
                c.create_line(0, 1, 20, 1, fill=color, width=2, dash=(3, 2))
            else:
                c.create_line(0, 1, 20, 1, fill=color, width=2)
            tk.Label(lr, text=label, fg="#aaa", bg=pbg, font=("Segoe UI", 8)).pack(side="left")

        # Warnings legend
        tk.Frame(pf, bg="#2a2a45", height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(pf, text="BADGES", font=("Segoe UI", 9, "bold"), fg="#666", bg=pbg).pack(padx=12, anchor="w")
        for lbl, clr in [("Warning (unassigned/orphan)", WARN_COLOR), ("Error (broken link)", ERROR_COLOR)]:
            lr = tk.Frame(pf, bg=pbg)
            lr.pack(fill="x", padx=12, pady=1)
            c = tk.Canvas(lr, width=10, height=10, bg=pbg, highlightthickness=0)
            c.pack(side="left", padx=(0, 4))
            c.create_oval(1, 1, 9, 9, fill=clr, outline="")
            tk.Label(lr, text=lbl, fg="#aaa", bg=pbg, font=("Segoe UI", 7)).pack(side="left")

    # ---- SCANNING ----
    def trigger_scan(self):
        self.status_var.set("Scanning...")
        self.pending = "scan"

    def trigger_rescan(self):
        self.status_var.set("Re-scanning (keeping positions)...")
        self.pending = "rescan"

    def do_scan(self, preserve=False):
        devices = scan_level()
        verse_files = find_verse_files(self.path_var.get().strip())
        verse_data = [parse_verse(vf) for vf in verse_files]
        old = self.nodes if preserve else None
        self.nodes, self.edges, self.warnings = build_graph(devices, verse_data, old)

        w = max(self.canvas.winfo_width(), 800)
        h = max(self.canvas.winfo_height(), 600)
        layout_circle(self.nodes, w, h)
        self.draw()

        wc = sum(len(n.get("warnings", [])) for n in self.nodes)
        ec = sum(len(n.get("errors", [])) for n in self.nodes)
        self.warn_label.configure(text=f"{wc} warnings, {ec} errors" if wc + ec > 0 else "")
        self.status_var.set(
            f"{len(self.nodes)} devices | {len(self.edges)} connections | "
            f"{len(verse_files)} verse | {wc}W {ec}E"
        )

    def force_relayout(self):
        for n in self.nodes:
            n["x"] = 0; n["y"] = 0
        w = max(self.canvas.winfo_width(), 800)
        h = max(self.canvas.winfo_height(), 600)
        layout_circle(self.nodes, w, h)
        self.draw()

    # ---- ZOOM ----
    def set_zoom(self, delta):
        self.zoom = max(0.4, min(2.5, self.zoom + delta))
        self.zoom_label.configure(text=f"{int(self.zoom * 100)}%")
        self.draw()

    def on_scroll(self, event):
        d = 0.1 if event.delta > 0 else -0.1
        self.set_zoom(d)

    # ---- FILTER / SEARCH ----
    def on_filter(self):
        self.hidden_types = {k for k, v in self.filter_vars.items() if not v.get()}
        self.draw()

    def on_search(self):
        self.search_term = self.search_var.get().strip().lower()
        self.draw()

    def is_visible(self, node):
        if node["type_key"] in self.hidden_types: return False
        if self.search_term and self.search_term not in node["label"].lower(): return False
        return True

    # ---- FOCUS / TELEPORT ----
    def focus_selected(self):
        if not self.selected or not self.selected.get("actor"):
            self.status_var.set("No level actor to select")
            return
        sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        sub.select_nothing()
        sub.set_actor_selection_state(self.selected["actor"], True)
        try:
            unreal.EditorLevelLibrary.pilot_level_actor(self.selected["actor"])
            unreal.EditorLevelLibrary.eject_pilot_level_actor()
        except: pass
        self.status_var.set(f"Selected: {self.selected['label']} - press F to focus")

    def open_vscode(self):
        if not self.selected or not self.selected.get("verse_path"):
            self.status_var.set("No Verse file linked to this device")
            return
        path = self.selected["verse_path"]
        try:
            subprocess.Popen(["code", path], shell=True)
            self.status_var.set(f"Opened {self.selected['verse_file']} in VS Code")
        except:
            try:
                os.startfile(path)
                self.status_var.set(f"Opened {self.selected['verse_file']}")
            except:
                self.status_var.set("Could not open file")

    # ---- NOTE ----
    def on_note_change(self, event):
        if self.selected:
            self.selected["note"] = self.note_text.get("1.0", tk.END).strip()

    # ---- EXPORT ----
    def export_image(self):
        try:
            path = filedialog.asksaveasfilename(defaultextension=".ps",
                                                 filetypes=[("PostScript", "*.ps"), ("All", "*.*")],
                                                 title="Export Graph")
            if path:
                self.canvas.postscript(file=path, colormode="color")
                self.status_var.set(f"Exported to {path}")
        except Exception as e:
            self.status_var.set(f"Export failed: {e}")

    def export_text(self):
        try:
            path = filedialog.asksaveasfilename(defaultextension=".txt",
                                                 filetypes=[("Text", "*.txt"), ("All", "*.*")],
                                                 title="Export Summary")
            if not path: return
            with open(path, 'w') as f:
                f.write("UEFN DEVICE GRAPH SUMMARY\n")
                f.write("=" * 50 + "\n\n")

                f.write(f"Devices: {len(self.nodes)}\n")
                f.write(f"Connections: {len(self.edges)}\n")
                f.write(f"Warnings: {sum(len(n.get('warnings',[])) for n in self.nodes)}\n")
                f.write(f"Errors: {sum(len(n.get('errors',[])) for n in self.nodes)}\n\n")

                f.write("DEVICES\n" + "-" * 30 + "\n")
                for n in self.nodes:
                    f.write(f"\n{n['label']} ({n['class']})\n")
                    f.write(f"  Position: {n['loc']}\n")
                    if n.get("verse_file"):
                        f.write(f"  Verse: {n['verse_file']}\n")
                    if n.get("note"):
                        f.write(f"  Note: {n['note']}\n")
                    for e in n.get("editables", []):
                        f.write(f"  @editable {e['name']}: {e['type']}\n")
                    for e in n.get("events", []):
                        f.write(f"  Event: {e['source']}.{e['event']} -> {e['handler']}\n")
                    for w in n.get("warnings", []):
                        f.write(f"  WARNING: {w}\n")
                    for e in n.get("errors", []):
                        f.write(f"  ERROR: {e}\n")

                f.write("\nCONNECTIONS\n" + "-" * 30 + "\n")
                for e in self.edges:
                    fn = next((n["label"] for n in self.nodes if n["id"] == e["from"]), "?")
                    tn = next((n["label"] for n in self.nodes if n["id"] == e["to"]), "?")
                    f.write(f"  {fn} --[{e['label']}]--> {tn} ({e['type']})\n")

                if self.warnings:
                    f.write("\nALL WARNINGS\n" + "-" * 30 + "\n")
                    for w in self.warnings:
                        f.write(f"  {w}\n")

            self.status_var.set(f"Exported to {path}")
        except Exception as e:
            self.status_var.set(f"Export failed: {e}")

    # ---- DRAWING ----
    def draw(self):
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 800)
        ch = max(self.canvas.winfo_height(), 600)
        z = self.zoom

        # Grid
        step = int(40 * z)
        if step > 5:
            for x in range(0, cw, step):
                self.canvas.create_line(x, 0, x, ch, fill="#10101e")
            for y in range(0, ch, step):
                self.canvas.create_line(0, y, cw, y, fill="#10101e")

        # Visible nodes
        visible = [n for n in self.nodes if self.is_visible(n)]
        vis_ids = {n["id"] for n in visible}

        # Edges
        for edge in self.edges:
            if edge["from"] not in vis_ids or edge["to"] not in vis_ids: continue
            fn = next((n for n in self.nodes if n["id"] == edge["from"]), None)
            tn = next((n for n in self.nodes if n["id"] == edge["to"]), None)
            if not fn or not tn: continue

            nw = self.NW * z; nh = self.NH * z
            x1 = fn["x"] * z + nw / 2
            y1 = fn["y"] * z + nh / 2
            x2 = tn["x"] * z + nw / 2
            y2 = tn["y"] * z + nh / 2

            color = edge["color"]
            dash = (5, 3) if edge["type"] == "event" else ()

            dx = x2 - x1; dy = y2 - y1
            dist = math.sqrt(dx*dx + dy*dy) or 1
            off = min(25 * z, dist * 0.1)
            px = (x1+x2)/2 + (-dy/dist) * off
            py = (y1+y2)/2 + (dx/dist) * off

            self.canvas.create_line(x1, y1, px, py, x2, y2,
                                     fill=color, width=max(1, int(2*z)), dash=dash, smooth=True)

            angle = math.atan2(y2-py, x2-px)
            al = 7 * z
            ax1 = x2 - al * math.cos(angle - 0.5)
            ay1 = y2 - al * math.sin(angle - 0.5)
            ax2 = x2 - al * math.cos(angle + 0.5)
            ay2 = y2 - al * math.sin(angle + 0.5)
            self.canvas.create_polygon(x2, y2, ax1, ay1, ax2, ay2, fill=color)

            if z > 0.6:
                self.canvas.create_text(px + 5, py - 8, text=edge["label"],
                                         fill="#555", font=("Segoe UI", max(6, int(7*z))), anchor="w")

        # Nodes
        for node in visible:
            self.draw_node(node, z)

    def draw_node(self, node, z):
        x = node["x"] * z; y = node["y"] * z
        w = self.NW * z; h = self.NH * z
        color = node["color"]
        is_sel = self.selected and self.selected["id"] == node["id"]
        has_warn = len(node.get("warnings", [])) > 0
        has_err = len(node.get("errors", [])) > 0
        has_note = bool(node.get("note"))

        # Search highlight
        is_match = self.search_term and self.search_term in node["label"].lower()

        # Glow
        if is_sel:
            for i in range(3):
                p = (3 - i) * 3 * z
                self.canvas.create_rectangle(x-p, y-p, x+w+p, y+h+p,
                                              outline=color, width=1, dash=(2, 4))

        # Shadow
        self.canvas.create_rectangle(x+2*z, y+2*z, x+w+2*z, y+h+2*z, fill="#050508", outline="")

        # Body
        outline = "white" if is_sel else ("#ffff00" if is_match else "#222240")
        self.canvas.create_rectangle(x, y, x+w, y+h, fill="#141428",
                                      outline=outline, width=2 if is_sel or is_match else 1)

        # Left color bar
        self.canvas.create_rectangle(x, y, x + 4*z, y + h, fill=color, outline="")
        # Top line
        self.canvas.create_rectangle(x, y, x + w, y + 2*z, fill=color, outline="")

        if z > 0.5:
            # Label
            fs = max(7, int(9 * z))
            label = node["label"]
            maxc = int(24 / max(z, 0.5))
            if len(label) > maxc: label = label[:maxc-2] + ".."
            self.canvas.create_text(x + 10*z, y + 20*z, text=label,
                                     fill="white", font=("Segoe UI", fs, "bold"), anchor="w")

            # Class
            cn = node["class"].replace("Device_", "").replace("_C", "").replace("_V2", "").replace("_V3", "")
            if len(cn) > 28: cn = cn[:26] + ".."
            self.canvas.create_text(x + 10*z, y + 38*z, text=cn,
                                     fill="#666", font=("Segoe UI", max(6, int(7*z))), anchor="w")

        # Connection badge
        ec = sum(1 for e in self.edges if e["from"] == node["id"] or e["to"] == node["id"])
        if ec > 0:
            bx, by = x + w - 14*z, y + h - 14*z
            br = 8 * z
            self.canvas.create_oval(bx-br, by-br, bx+br, by+br, fill=color, outline="")
            self.canvas.create_text(bx, by, text=str(ec), fill="white",
                                     font=("Segoe UI", max(6, int(8*z)), "bold"))

        # Warning badge
        if has_err:
            bx, by = x + w - 14*z, y + 14*z
            br = 7 * z
            self.canvas.create_oval(bx-br, by-br, bx+br, by+br, fill=ERROR_COLOR, outline="")
            self.canvas.create_text(bx, by, text="!", fill="white",
                                     font=("Segoe UI", max(6, int(8*z)), "bold"))
        elif has_warn:
            bx, by = x + w - 14*z, y + 14*z
            br = 7 * z
            self.canvas.create_oval(bx-br, by-br, bx+br, by+br, fill=WARN_COLOR, outline="")
            self.canvas.create_text(bx, by, text="!", fill="black",
                                     font=("Segoe UI", max(6, int(8*z)), "bold"))

        # Note indicator
        if has_note and z > 0.5:
            self.canvas.create_text(x + 10*z, y + h - 8*z, text="NOTE",
                                     fill="#888", font=("Segoe UI", max(5, int(6*z))), anchor="w")

        # Verse indicator
        if node.get("verse_file") and z > 0.5:
            self.canvas.create_text(x + w - 30*z, y + h - 8*z, text="VS",
                                     fill="#e94560", font=("Segoe UI", max(5, int(6*z)), "bold"), anchor="w")

    # ---- INTERACTION ----
    def find_node(self, mx, my):
        z = self.zoom
        for node in reversed(self.nodes):
            nx = node["x"] * z; ny = node["y"] * z
            nw = self.NW * z; nh = self.NH * z
            if nx <= mx <= nx + nw and ny <= my <= ny + nh:
                if self.is_visible(node):
                    return node
        return None

    def on_click(self, event):
        node = self.find_node(event.x, event.y)
        if node:
            self.drag_node = node
            self.drag_off = (event.x / self.zoom - node["x"], event.y / self.zoom - node["y"])
            self.selected = node
            self.show_info(node)
            if node.get("actor"):
                try:
                    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    sub.select_nothing()
                    sub.set_actor_selection_state(node["actor"], True)
                except: pass
        else:
            self.selected = None
            self.clear_info()
        self.draw()

    def on_double_click(self, event):
        node = self.find_node(event.x, event.y)
        if node:
            self.selected = node
            self.show_info(node)
            self.focus_selected()
            self.draw()

    def on_drag(self, event):
        if self.drag_node:
            self.drag_node["x"] = event.x / self.zoom - self.drag_off[0]
            self.drag_node["y"] = event.y / self.zoom - self.drag_off[1]
            self.draw()

    def on_release(self, event):
        self.drag_node = None

    def show_info(self, node):
        self.info_name.configure(text=node["label"])
        cn = node["class"].replace("Device_", "").replace("_C", "")
        self.info_class.configure(text=cn)
        loc = node["loc"]
        self.info_loc.configure(text=f"X: {loc[0]:.0f}  Y: {loc[1]:.0f}  Z: {loc[2]:.0f}")

        self.warn_text.delete("1.0", tk.END)
        for w in node.get("warnings", []):
            self.warn_text.insert(tk.END, f"W: {w}\n")
        for e in node.get("errors", []):
            self.warn_text.insert(tk.END, f"E: {e}\n")
        if not node.get("warnings") and not node.get("errors"):
            self.warn_text.insert(tk.END, "No issues")

        self.edit_text.delete("1.0", tk.END)
        for e in node.get("editables", []):
            self.edit_text.insert(tk.END, f"{e['name']}: {e['type']}\n")
        if not node.get("editables"):
            self.edit_text.insert(tk.END, "none")

        self.event_text.delete("1.0", tk.END)
        for e in node.get("events", []):
            self.event_text.insert(tk.END, f"{e['source']}.{e['event']}\n  -> {e['handler']}\n")
        if not node.get("events"):
            self.event_text.insert(tk.END, "none")

        self.func_text.delete("1.0", tk.END)
        fns = node.get("functions", [])
        called = node.get("called_functions", set())
        for fn in fns:
            used = "USED" if fn in called or fn in ["OnBegin", "OnEnd"] else "UNUSED"
            tag = "" if used == "USED" else " [UNUSED]"
            self.func_text.insert(tk.END, f"{fn}(){tag}\n")
        for c in node.get("calls", []):
            self.func_text.insert(tk.END, f"  calls {c['target']}.{c['func']}()\n")
        if not fns and not node.get("calls"):
            self.func_text.insert(tk.END, "none")

        self.note_text.delete("1.0", tk.END)
        self.note_text.insert(tk.END, node.get("note", ""))

        vf = node.get("verse_file", "")
        self.verse_label.configure(text=f"Verse: {vf}" if vf else "No Verse file")

    def clear_info(self):
        self.info_name.configure(text="No device selected")
        self.info_class.configure(text="")
        self.info_loc.configure(text="")
        self.warn_text.delete("1.0", tk.END)
        self.edit_text.delete("1.0", tk.END)
        self.event_text.delete("1.0", tk.END)
        self.func_text.delete("1.0", tk.END)
        self.note_text.delete("1.0", tk.END)
        self.verse_label.configure(text="")

    # ---- TICK ----
    def start_tick(self):
        def on_tick(dt):
            try:
                if not self.root.winfo_exists():
                    self.stop_tick()
                    return
                if self.pending == "scan":
                    self.pending = None
                    self.do_scan(False)
                elif self.pending == "rescan":
                    self.pending = None
                    self.do_scan(True)
                self.root.update()
            except tk.TclError:
                self.stop_tick()

        self.tick_handle = unreal.register_slate_post_tick_callback(on_tick)
        unreal.log("Device Graph v3 opened.")

    def stop_tick(self):
        if self.tick_handle:
            unreal.unregister_slate_post_tick_callback(self.tick_handle)
            self.tick_handle = None
            unreal.log("Device Graph v3 closed.")

NodeGraphApp()
