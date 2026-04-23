import tkinter as tk
from tkinter import ttk
import requests
import threading
import urllib.parse
import webbrowser
import logging
import os
import json
import time
import tempfile
import platform
import re
import traceback
from config import config
import myNotebook as nb

try:
    import monitor
except ImportError:
    monitor = None

# Plugin metadata
plugin_name = "RavenColonialSync"
plugin_version = "8.4.3"

RCC_API_BASE = "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
RCC_UX_BASE = "https://ravencolonial.com"

# -------------------------------------------------------------------------
# IN-MEMORY LOGGER
# -------------------------------------------------------------------------
logger = logging.getLogger(plugin_name)
logger.setLevel(logging.DEBUG)

try:
    log_file_path = os.path.expanduser('~/raven_debuglog.md')
    with open(log_file_path, 'a') as f: f.write("")
except Exception:
    log_file_path = os.path.join(tempfile.gettempdir(), 'raven_debuglog.md')

if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    try:
        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('### %(asctime)s - %(levelname)s\n```json\n%(message)s\n```\n---')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"[{plugin_name}] Logger initialized at {log_file_path}")
    except Exception:
        pass

class MemoryLog:
    def __init__(self):
        self.logs = []
    def append(self, msg):
        timestamp = time.strftime('%H:%M:%S')
        self.logs.insert(0, f"[{timestamp}] {msg}")
        if len(self.logs) > 150: self.logs.pop()

mem_log = MemoryLog()

def log_info(msg):
    logger.info(msg)
    mem_log.append(f"INFO: {msg}")

def log_error(msg):
    logger.error(msg)
    mem_log.append(f"ERROR: {msg}")

def log_debug(msg):
    logger.debug(msg)
    mem_log.append(f"DEBUG: {msg}")

# -------------------------------------------------------------------------
# COMMODITY MAPPING & FORMATTING
# -------------------------------------------------------------------------
_C_RAW = {
    "Chemicals": ["Liquid Oxygen", "Water", "Explosives", "Hydrogen Fuel", "Hydrogen Peroxide", "Mineral Oil"],
    "Consumer Items": ["Clothing", "Consumer Technology", "Domestic Appliances", "Evacuation Shelter", "Survival Equipment"],
    "Foods": ["Algae", "Animal Meat", "Coffee", "Fish", "Food Cartridges", "Fruit and Vegetables", "Synthetic Meat", "Tea"],
    "Industrial Materials": ["Ceramic Composites", "Polymers", "Semiconductors", "Superconductors", "Meta-Alloys", "CMM Composite", "Insulating Membrane"],
    "Machinery": ["Atmospheric Extractors", "Building Fabricators", "Crop Harvesters", "Emergency Power Cells", "Exhaust Manifold", "Geological Equipment", "HN Shock Mount", "Marine Supplies", "Mineral Extractors", "Power Generators", "Thermal Cooling Units", "Water Purifiers"],
    "Medicines": ["Advanced Medicines", "Agri-Medicines", "Basic Medicines", "Combat Stabilisers", "Performance Enhancers", "Progenitor Cells", "Medical Diagnostic Equipment"],
    "Metals": ["Aluminium", "Copper", "Gold", "Iron", "Palladium", "Platinum", "Silver", "Steel", "Titanium", "Uranium", "Cobalt", "Gallium", "Indium", "Lithium", "Osmium", "Tantalum", "Bismuth"],
    "Minerals": ["Bauxite", "Bertrandite", "Coltan", "Cryolite", "Gallite", "Goshenite", "Indite", "Jadeite", "Lepidolite", "Lithium Hydroxide", "Moissanite", "Painite", "Pyrophyllite", "Rutile", "Taaffeite", "Uraninite"],
    "Technology": ["Advanced Catalysers", "Ani-Monitors", "Aquaponic Systems", "Auto-Fabricators", "Bioreducing Lichen", "Computer Components", "H.E. Suits", "Land Enrichment Systems", "Micro Controllers", "Muon Imager", "Nanobreakers", "Resonating Separators", "Robotics", "Structural Regulators", "Telemetry Suite", "Surface Stabilisers"],
    "Weapons": ["Non-Lethal Weapons", "Personal Weapons", "Reactive Armour", "Battle Weapons"]
}
COMMODITY_DATA = {name.lower().replace("-", "").replace(".", "").replace(" ", ""): {"cat": cat, "name": name} for cat, items in _C_RAW.items() for name in items}

# -------------------------------------------------------------------------
# HTTP CLIENT & GLOBALS
# -------------------------------------------------------------------------
session = requests.Session()
session.headers.update({'User-Agent': f'EDMC-RavenColonialSync/{plugin_version}', 'Accept': 'application/json'})

current_system = {
    "name": "Unknown",
    "address": 0,
    "pos": [0.0, 0.0, 0.0]
}

active_project = {
    "is_active": False,
    "name": "",
    "target_body": "",
    "build_type": "",
    "system_site_id": None,
    "build_id": None,
    "market_id": 0,
    "force_bypass": False,
    "manual_cargo_dict": {},
    "auto_open_browser": False,
    "progress_data": {}
}

latest_market_data = {
    "market_id": 0,
    "demands": {}
}

active_route_target = {
    "system": "",
    "jumps_left": 0,
    "star_class": "",
    "last_fetched_sys": "",
    "last_info_str": ""
}

system_colonial_report = []
system_scans_cache = {}
system_stations_cache = {}
last_docked_station = {"name": "", "market_id": 0}

BUILD_TYPES_MAP = {}
BUILD_CARGO_MAP = {}
overlay_toggle_var = None
tools_frame_ref = None
actions_frame_ref = None
main_error_label = None

def show_edmc_error():
    if main_error_label and main_error_label.winfo_exists():
        try: main_error_label.after(0, lambda: main_error_label.config(text="Plugin Error: Check log for details."))
        except Exception: pass

# -------------------------------------------------------------------------
# HELPERS & PERSISTENT MEMORY
# -------------------------------------------------------------------------
def get_cmdr_name():
    name = config.get_str("RCC_CmdrName")
    if name and name.strip(): return name.strip()
    name = config.get_str("commander_name")
    if name and name.strip(): return name.strip()
    return "UnknownCmdr"

def clean_station_name(name):
    if not name: return ""
    pattern = r"^(system coloni[sz]ation ship|planetary construction site|orbital construction site)[:\-\s]+"
    return re.sub(pattern, "", name.strip(), flags=re.IGNORECASE).strip()

def save_active_project():
    config.set("RCC_ActiveBuildId", active_project.get("build_id") or "")
    config.set("RCC_ActiveName", active_project.get("name") or "")
    config.set("RCC_ActiveMarketId", str(active_project.get("market_id") or "0"))
    config.set("RCC_ActiveBuildType", active_project.get("build_type") or "")
    config.set("RCC_ActiveTargetBody", active_project.get("target_body") or "")

def restore_active_project():
    b_id = config.get_str("RCC_ActiveBuildId")
    if b_id:
        active_project["is_active"] = True
        active_project["build_id"] = b_id
        active_project["name"] = config.get_str("RCC_ActiveName") or "Unknown"
        active_project["build_type"] = config.get_str("RCC_ActiveBuildType") or ""
        active_project["target_body"] = config.get_str("RCC_ActiveTargetBody") or ""
        try: active_project["market_id"] = int(config.get_str("RCC_ActiveMarketId") or "0")
        except ValueError: active_project["market_id"] = 0

def unlink_project():
    global active_project
    active_project.update({
        "is_active": False, "name": "", "target_body": "", "build_type": "",
        "system_site_id": None, "build_id": None, "market_id": 0,
        "force_bypass": False, "manual_cargo_dict": {}, "progress_data": {}
    })
    save_active_project()
    if hud_instance: hud_instance.update_system(current_system['name'], force_show=True)
    log_info("Successfully unlinked the current project.")

def set_current_system(name, addr, pos):
    global current_system
    if not name or name == "Unknown": return
    changed = (current_system['name'] != name)
    current_system['name'] = name
    if addr != 0 or current_system['address'] == 0: current_system['address'] = addr
    if pos != [0.0, 0.0, 0.0] or current_system['pos'] == [0.0, 0.0, 0.0]: current_system['pos'] = pos

    config.set("RCC_SysName", current_system['name'])
    config.set("RCC_SysAddr", str(current_system['address']))
    config.set("RCC_SysPosX", str(current_system['pos'][0]))
    config.set("RCC_SysPosY", str(current_system['pos'][1]))
    config.set("RCC_SysPosZ", str(current_system['pos'][2]))

    if changed: trigger_system_update(name)

def set_last_docked(name, m_id):
    global last_docked_station
    if not name: return
    try: m_id = int(m_id) if m_id else 0
    except ValueError: m_id = 0
    last_docked_station["name"] = name
    last_docked_station["market_id"] = m_id
    config.set("RCC_LastStationName", name)
    config.set("RCC_LastMarketID", str(m_id))

def resolve_market_id(target_name):
    if not target_name: return 0
    target_lower = clean_station_name(target_name).lower()

    if monitor and getattr(monitor, 'state', None):
        m_id = monitor.state.get("MarketID")
        s_name = clean_station_name(monitor.state.get("StationName", "")).lower()
        if m_id and str(m_id) != "0" and s_name:
            if s_name == target_lower or s_name in target_lower or target_lower in s_name: return m_id

    if last_docked_station["market_id"] and str(last_docked_station["market_id"]) != "0":
        ld_name = clean_station_name(last_docked_station["name"]).lower()
        if ld_name and (ld_name == target_lower or ld_name in target_lower or target_lower in ld_name): return last_docked_station["market_id"]

    for s_name, m_id in system_stations_cache.items():
        s_name_lower = clean_station_name(s_name).lower()
        if m_id and str(m_id) != "0":
            if s_name_lower == target_lower or s_name_lower in target_lower or target_lower in s_name_lower: return m_id
    return 0

# -------------------------------------------------------------------------
# DATA LOADING
# -------------------------------------------------------------------------
def load_build_data(plugin_dir):
    global BUILD_TYPES_MAP, BUILD_CARGO_MAP
    costs_path = os.path.join(plugin_dir, 'colonization-costs2.json')
    try:
        if os.path.exists(costs_path):
            with open(costs_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                for item in data:
                    name = item.get("displayName", "Unknown")
                    btype = item.get("buildType", "unknown")
                    cargo = item.get("cargo", {})
                    BUILD_TYPES_MAP[name] = btype
                    BUILD_CARGO_MAP[str(btype).lower()] = cargo
                    for layout in item.get("layouts", []): BUILD_CARGO_MAP[str(layout).lower()] = cargo
            return
    except Exception as e: log_error(f"Error reading JSON: {e}")

def get_colonial_buffs(body):
    buffs = set()
    subType = body.get('subType', '')
    if subType == 'Earthlike body': buffs.update(["Agriculture", "HighTech", "Military", "Tourism", "Huge Pop Boost"])
    elif subType == 'Water world': buffs.update(["Agriculture", "Tourism", "Large Pop Boost"])
    elif subType == 'Ammonia world': buffs.update(["HighTech", "Tourism"])
    elif 'Gas giant' in subType or 'water giant' in subType.lower(): buffs.update(["HighTech", "Industrial"])
    elif subType in ['High metal content body', 'Metal rich body']: buffs.update(["Extraction"])
    elif subType == 'Rocky ice body': buffs.update(["Industrial", "Refinery"])
    elif subType == 'Rocky body': buffs.update(["Refinery"])
    elif subType == 'Icy body': buffs.update(["Industrial"])
    elif body.get('type') == 'Star':
        if subType in ['Black hole', 'Neutron Star', 'White Dwarf']: buffs.update(["HighTech", "Tourism"])
        else: buffs.update(["Military"])

    if body.get('rings'): buffs.add("Extraction (Rings)")
    signals = body.get('signals', {})
    if signals.get('Biological', 0) > 0: buffs.update(["Agriculture", "Terraforming"])
    if body.get('volcanismType') or signals.get('Geological', 0) > 0: buffs.update(["Extraction"])
    return ", ".join(sorted(buffs)) if buffs else "None"

# -------------------------------------------------------------------------
# UI CLASSES
# -------------------------------------------------------------------------
class OverlayHUD:
    def __init__(self):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        try: self.root.attributes("-transparentcolor", "black")
        except tk.TclError: pass
        self.root.config(bg="black")

        self.reposition_mode = False
        self._drag_data = {"x": 0, "y": 0}

        self.system_var = tk.StringVar(value="Raven Colonial: Standby")
        self.project_var = tk.StringVar(value="")
        self.jump_var = tk.StringVar(value="")
        self.signal_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.progress_var = tk.StringVar(value="")

        self.hide_timer = None

        self.lbl_system = tk.Label(self.root, textvariable=self.system_var, fg="#ff8c00", bg="black")
        self.lbl_system.pack(pady=(10, 0), padx=15)
        self.lbl_project = tk.Label(self.root, textvariable=self.project_var, fg="#00ff00", bg="black")
        self.lbl_project.pack(pady=(2, 0), padx=15)

        self.lbl_jump = tk.Label(self.root, textvariable=self.jump_var, fg="#aaaaaa", bg="black", font=("Arial", 9, "italic"))
        self.lbl_jump.pack(pady=(2, 5), padx=15, fill=tk.X)

        self.lbl_signal = tk.Label(self.root, textvariable=self.signal_var, fg="#00ffff", bg="black")
        self.lbl_signal.pack(pady=(5, 0), padx=15)
        self.lbl_status = tk.Label(self.root, textvariable=self.status_var, fg="#aaaaaa", bg="black")
        self.lbl_status.pack(pady=(5, 0), padx=15)
        self.lbl_progress = tk.Label(self.root, textvariable=self.progress_var, bg="black", justify=tk.LEFT, anchor="n")
        self.lbl_progress.pack(pady=(10, 15), padx=15, fill=tk.BOTH, expand=True)

        self.apply_settings()
        self.root.withdraw()

    def safe_execute(self, func, *args, **kwargs):
        try:
            if self.root.winfo_exists(): self.root.after(0, func, *args, **kwargs)
        except Exception: pass

    def _set_clickthrough(self, clickthrough):
        """Modifies Windows window styles to allow or block mouse clicks."""
        if platform.system() == "Windows":
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                if clickthrough:
                    # Add WS_EX_TRANSPARENT (0x00000020) and WS_EX_LAYERED (0x00080000)
                    ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
                else:
                    # Remove WS_EX_TRANSPARENT so the window can be clicked
                    ctypes.windll.user32.SetWindowLongW(hwnd, -20, (style | 0x00080000) & ~0x00000020)
            except Exception as e:
                log_debug(f"Clickthrough toggle failed: {e}")

    def toggle_reposition(self):
        self.safe_execute(self._toggle_reposition)

    def _toggle_reposition(self):
        self.reposition_mode = not self.reposition_mode
        if self.reposition_mode:
            # Crucial: disable click-through on Windows so you can actually click the window
            self._set_clickthrough(False)
            self.root.config(bg="#333333")
            try: self.root.attributes("-transparentcolor", "")
            except tk.TclError: pass

            # Force full opacity to easily see the window
            self.root.attributes("-alpha", 1.0)

            for lbl in [self.lbl_system, self.lbl_project, self.lbl_jump, self.lbl_signal, self.lbl_status, self.lbl_progress]:
                lbl.config(bg="#333333")

            self.root.bind("<ButtonPress-1>", self.on_drag_start)
            self.root.bind("<B1-Motion>", self.on_drag_motion)
            self.system_var.set("[DRAG TO REPOSITION - CLICK TOGGLE TO SAVE]")
            self._show_hud()
        else:
            self.root.unbind("<ButtonPress-1>")
            self.root.unbind("<B1-Motion>")
            geom = self.root.geometry()
            match = re.search(r'([+-]\d+[+-]\d+)', geom)
            if match: config.set("RCC_HUDGeometry", match.group(1))
            self._apply_settings()
            self.update_system(current_system['name'], force_show=True)

    def on_drag_start(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def on_drag_motion(self, event):
        x = self.root.winfo_pointerx() - self._drag_data["x"]
        y = self.root.winfo_pointery() - self._drag_data["y"]
        self.root.geometry(f"+{x}+{y}")

    def apply_settings(self): self.safe_execute(self._apply_settings)
    def _apply_settings(self):
        try: opacity = float(config.get_str("RCC_HUDOpacity") or "1.0")
        except ValueError: opacity = 1.0

        try: scale = float(config.get_str("RCC_HUDScale") or "100") / 100.0
        except ValueError: scale = 1.0

        color_map = {"Orange": "#ffcc00", "Green": "#00ff00", "Cyan": "#00ffff", "White": "#ffffff"}
        c_hex = color_map.get(config.get_str("RCC_HUDColor") or "Orange", "#ffcc00")

        align_str = config.get_str("RCC_HUDAlign") or "Left"
        anchor_map = {"Left": "nw", "Center": "n", "Right": "ne"}
        justify_map = {"Left": tk.LEFT, "Center": tk.CENTER, "Right": tk.RIGHT}

        always_on_top = config.get_str("RCC_HUDAlwaysOnTop") != "0"
        try: self.root.attributes("-topmost", always_on_top)
        except Exception: pass

        geom = config.get_str("RCC_HUDGeometry")
        if geom: self.root.geometry(geom)
        else: self.root.geometry("+50+50")

        bg_mode = config.get_str("RCC_HUDBgMode") or "Transparent"
        if not self.reposition_mode:
            # Re-enable click-through when we aren't dragging it
            self._set_clickthrough(True)
            self.root.config(bg="black")
            for lbl in [self.lbl_system, self.lbl_project, self.lbl_jump, self.lbl_signal, self.lbl_status, self.lbl_progress]:
                lbl.config(bg="black")

            if bg_mode == "Transparent":
                try: self.root.attributes("-transparentcolor", "black")
                except: pass
            else:
                try: self.root.attributes("-transparentcolor", "")
                except: pass

            self.root.attributes("-alpha", opacity)

        self.lbl_system.config(font=("Arial", int(14 * scale), "bold"), fg="#ff8c00")
        self.lbl_project.config(font=("Arial", int(10 * scale), "italic"), fg="#00ff00")

        self.lbl_jump.config(
            font=("Arial", int(9 * scale), "italic"),
            fg="#aaaaaa",
            justify=justify_map.get(align_str, tk.LEFT)
        )

        self.lbl_signal.config(font=("Arial", int(11 * scale)), fg="#00ffff")
        self.lbl_status.config(font=("Arial", int(9 * scale)), fg="#aaaaaa")

        self.lbl_progress.config(
            font=("Consolas", int(9 * scale)),
            fg=c_hex,
            anchor=anchor_map.get(align_str, "nw"),
            justify=justify_map.get(align_str, tk.LEFT)
        )

        if config.get_str("RCC_HUDShowJump") == "0": self.jump_var.set("")

    def show_hud(self): self.safe_execute(self._show_hud)
    def _show_hud(self):
        if config.get_str("RCC_EnableOverlay") == "0":
            self.root.withdraw()
            return

        self.root.deiconify()
        self.root.update()

        try: auto_hide = int(config.get_str("RCC_HUDAutoHide") or "0")
        except ValueError: auto_hide = 0

        if self.hide_timer:
            self.root.after_cancel(self.hide_timer)
            self.hide_timer = None

        if auto_hide > 0 and not self.reposition_mode:
            self.hide_timer = self.root.after(auto_hide * 1000, self.root.withdraw)

    def hide_hud(self): self.safe_execute(self.root.withdraw)
    def update_system(self, system_name, force_show=False):
        self.safe_execute(self._update_system, system_name, force_show)

    def _update_system(self, system_name, force_show):
        if self.reposition_mode: return
        changed = False
        new_sys = f"Target: {system_name}"
        if self.system_var.get() != new_sys:
            self.system_var.set(new_sys)
            changed = True

        self.signal_var.set("Polling EDSM network...")
        self.status_var.set("Syncing to Raven Colonial...")

        if config.get_str("RCC_HUDShowAllProjects") == "1": new_proj = "System Projects:"
        else:
            display_name = clean_station_name(active_project['name'])
            new_proj = f"Project: {display_name} ({active_project['build_type']})" if active_project["is_active"] else ""

        if self.project_var.get() != new_proj:
            self.project_var.set(new_proj)
            changed = True
            if not active_project["is_active"] and config.get_str("RCC_HUDShowAllProjects") != "1":
                self.progress_var.set("")

        if changed or force_show: self._show_hud()

    def update_signals(self, text, force_show=False):
        self.safe_execute(self._update_signals, text, force_show)
    def _update_signals(self, text, force_show):
        if self.reposition_mode: return
        if self.signal_var.get() != text:
            self.signal_var.set(text)
            self._show_hud()
        elif force_show: self._show_hud()

    def update_status(self, text, force_show=False):
        self.safe_execute(self._update_status, text, force_show)
    def _update_status(self, text, force_show):
        if self.reposition_mode: return
        if self.status_var.get() != text:
            self.status_var.set(text)
            self._show_hud()
        elif force_show: self._show_hud()

    def update_progress(self, projects_data, force_show=False):
        self.safe_execute(self._update_progress, projects_data, force_show)

    def _update_progress(self, projects_data, force_show):
        if self.reposition_mode: return
        if not projects_data:
            self.progress_var.set("")
            return

        lines = []
        for proj in projects_data:
            title = proj.get("title")
            demands = proj.get("demands", {})
            active_items = {k: v for k, v in demands.items() if v > 0}

            if not active_items:
                if title: lines.append(f"\n★★★ {title} - COMPLETED ★★★")
                elif len(projects_data) == 1: lines.append("\n\n★★★ CONSTRUCTION REQUIREMENTS MET! ★★★")
                continue

            if title: lines.append(f"\n[{title}]")
            elif len(projects_data) == 1: lines.append("--- Remaining Demand ---")

            grouped = {}
            for k, v in active_items.items():
                k_clean = k.lower().replace(" ", "").strip('$').split('_name')[0].replace(';', '')
                cat_info = COMMODITY_DATA.get(k_clean, {"cat": "Other", "name": k.title()})
                cat = cat_info["cat"]
                d_name = cat_info["name"]
                if cat not in grouped: grouped[cat] = []
                grouped[cat].append((d_name, v))

            sorted_cats = sorted(grouped.keys())
            for cat in sorted_cats:
                lines.append(f"--- {cat} ---")
                grouped[cat].sort(key=lambda x: x[0])
                for name, amount in grouped[cat]: lines.append(f"  {name}: {amount}")

        cols_setting = config.get_str("RCC_HUDColumns") or "Auto"
        use_2_cols = (cols_setting == "2 Columns") or (cols_setting == "Auto" and len(lines) > 15)
        if cols_setting == "1 Column": use_2_cols = False

        if use_2_cols:
            half = (len(lines) + 1) // 2
            col1 = lines[:half]
            col2 = lines[half:]
            final_lines = []
            for i in range(half):
                left = col1[i].ljust(45)
                right = col2[i] if i < len(col2) else ""
                final_lines.append(left + right)
            new_text = "\n".join(final_lines)
        else:
            new_text = "\n".join(lines).strip()

        if self.progress_var.get() != new_text:
            self.progress_var.set(new_text)
            self._show_hud()
        elif force_show: self._show_hud()

    def destroy(self): self.safe_execute(self.root.destroy)

class DebugLogMenu:
    def __init__(self, parent_frame):
        self.window = tk.Toplevel(parent_frame)
        self.window.title("Raven Colonial - Internal Debug Log")
        self.window.geometry("750x450")
        self.window.attributes("-topmost", True)
        text_widget = tk.Text(self.window, wrap=tk.WORD, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        log_content = "\n\n".join(mem_log.logs) if mem_log.logs else "No logs recorded yet..."
        text_widget.insert(tk.END, log_content)
        text_widget.config(state=tk.DISABLED)

class ColonialReportMenu:
    def __init__(self, parent_frame):
        self.window = tk.Toplevel(parent_frame)
        self.window.title(f"Colonial Report - {current_system['name']}")
        self.window.geometry("860x300")
        self.window.attributes("-topmost", True)

        columns = ("Body", "Features", "Colonial Buffs")
        self.tree = ttk.Treeview(self.window, columns=columns, show="headings")
        self.tree.heading("Body", text="Body")
        self.tree.heading("Features", text="Features")
        self.tree.heading("Colonial Buffs", text="Colonial Buffs")
        self.tree.column("Body", width=120, anchor="w")
        self.tree.column("Features", width=250, anchor="w")
        self.tree.column("Colonial Buffs", width=470, anchor="w")

        scrollbar = ttk.Scrollbar(self.window, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)

        if not system_colonial_report: self.tree.insert("", tk.END, values=("No Data", "No prime bodies or EDSM is still syncing.", ""))
        else:
            for item in system_colonial_report: self.tree.insert("", tk.END, values=(item['name'], item['tag'], item['buffs']))

class ManualEntryMenu:
    def __init__(self, parent_frame, base_cargo, display_name):
        self.window = tk.Toplevel(parent_frame)
        self.window.title("Manual Commodity Entry")
        self.window.geometry("380x450")
        self.window.attributes("-topmost", True)
        self.window.grab_set()

        self.display_name = display_name
        tk.Label(self.window, text="Enter Exact Live Market Requirements:", font=("Arial", 10, "bold")).pack(pady=(10, 5))

        container = tk.Frame(self.window)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas)

        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.entries = {}
        for row, (comm, amount) in enumerate(base_cargo.items()):
            d_name = COMMODITY_DATA.get(comm.lower(), {}).get("name", comm.title())
            tk.Label(self.scrollable_frame, text=d_name + ":").grid(row=row, column=0, sticky="e", padx=5, pady=2)
            var = tk.StringVar(value=str(amount))
            ent = tk.Entry(self.scrollable_frame, textvariable=var, width=15)
            ent.grid(row=row, column=1, sticky="w", padx=5, pady=2)
            self.entries[comm] = var

        btn_frame = tk.Frame(self.window)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Confirm & Link", command=self.submit).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=self.window.destroy).pack(side=tk.LEFT, padx=10)

    def submit(self):
        manual_data = {}
        for comm, var in self.entries.items():
            try:
                val = int(var.get().strip())
                if val > 0: manual_data[comm] = val
            except ValueError: pass

        global active_project
        active_project["manual_cargo_dict"] = manual_data
        active_project["force_bypass"] = True

        threading.Thread(target=create_raven_project_api, daemon=True).start()
        self.window.destroy()

class LinkProjectMenu:
    def __init__(self, parent_frame):
        self.window = tk.Toplevel(parent_frame)
        self.window.title(f"Link Project - {current_system['name']}")
        self.window.geometry("450x260")
        self.window.attributes("-topmost", True)
        self.window.grab_set()

        self.site_map = {}

        self.info_label = tk.Label(self.window, text="Fetching planned/active sites...", fg="#aaaaaa")
        self.info_label.pack(pady=(15, 5))

        self.site_combo = ttk.Combobox(self.window, state="disabled", width=60)
        self.site_combo.pack(pady=(5, 5))
        self.site_combo.bind("<<ComboboxSelected>>", self.on_select)

        tk.Label(self.window, text="Market ID (0 = Auto-detect failed, please type it manually):", fg="#aaaaaa").pack(pady=(10, 2))
        self.market_id_var = tk.StringVar(value="0")
        tk.Entry(self.window, textvariable=self.market_id_var, width=20, justify="center").pack(pady=(0, 10))

        self.browser_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.window, text="Auto-open project in browser", variable=self.browser_var).pack(pady=(0, 10))

        self.bypass_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.window, text="Manual Commodity Entry (Bypass Live Sync)", variable=self.bypass_var, fg="#ff7700").pack(pady=(0, 5))

        btn_frame = tk.Frame(self.window)
        btn_frame.pack(pady=5)
        self.start_btn = tk.Button(btn_frame, text="Link Project", state="disabled", command=self.start_project)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self.window.destroy).pack(side=tk.LEFT, padx=5)

        threading.Thread(target=self.fetch_planned_sites, daemon=True).start()

    def fetch_planned_sites(self):
        if current_system['name'] == "Unknown":
            self.window.after(0, self.show_error, "System unknown. Click 'Update' on EDMC main window.")
            return

        try:
            url = f"{RCC_API_BASE}/api/v2/system/{urllib.parse.quote(current_system['name'])}/sites"
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                sites = resp.json()
                planned_sites = [s for s in sites if s.get("status") in ["plan", "build"]]
                self.window.after(0, self.populate_dropdown, planned_sites)
            else:
                self.window.after(0, self.show_error, f"API Error: {resp.status_code}")
        except Exception:
            self.window.after(0, self.show_error, f"Network Error")

    def populate_dropdown(self, planned_sites):
        if not planned_sites:
            self.info_label.config(text="No planned or active sites found in this system.", fg="#ff4444")
            return

        self.info_label.config(text="Select a planned or active site to link:", fg="black")
        btype_to_display = {v: k for k, v in BUILD_TYPES_MAP.items()}
        combo_values = []
        for site in planned_sites:
            name = clean_station_name(site.get("name", "Unknown"))
            b_type = site.get("buildType", "Unknown")
            status = site.get("status", "plan").upper()
            display_type = btype_to_display.get(b_type, b_type)
            display_str = f"[{status}] {name} ({display_type})"
            self.site_map[display_str] = site
            combo_values.append(display_str)

        self.site_combo.config(values=combo_values, state="readonly")
        self.site_combo.current(0)
        self.on_select()
        self.start_btn.config(state="normal")

    def on_select(self, event=None):
        selection = self.site_combo.get()
        if not selection or selection not in self.site_map: return
        site_data = self.site_map[selection]
        db_market_id = site_data.get("marketId")
        if db_market_id and str(db_market_id) != "0": self.market_id_var.set(str(db_market_id))
        else: self.market_id_var.set(str(resolve_market_id(site_data.get("name", ""))))

    def show_error(self, error_msg):
        self.info_label.config(text=error_msg, fg="#ff4444")

    def start_project(self):
        selection = self.site_combo.get()
        if not selection or selection not in self.site_map: return
        site_data = self.site_map[selection]
        global active_project

        body_val = site_data.get("bodyName")
        if not body_val:
            body_num = site_data.get("bodyNum")
            body_val = str(body_num) if body_num is not None else ""

        manual_id_str = self.market_id_var.get().strip()
        market_id = int(manual_id_str) if manual_id_str.isdigit() else 0

        btype = str(site_data.get("buildType", ""))
        clean_name = clean_station_name(site_data.get("name", "Unknown"))

        active_project.update({
            "is_active": True,
            "name": clean_name,
            "target_body": body_val,
            "build_type": btype,
            "system_site_id": site_data.get("id", ""),
            "market_id": market_id,
            "build_id": site_data.get("buildId"),
            "force_bypass": False,
            "manual_cargo_dict": {},
            "auto_open_browser": self.browser_var.get(),
            "progress_data": BUILD_CARGO_MAP.get(btype.lower(), {}).copy()
        })

        if self.bypass_var.get():
            base_cargo = BUILD_CARGO_MAP.get(btype.lower(), {}).copy()
            ManualEntryMenu(self.window.master, base_cargo, clean_name)
            self.window.destroy()
            return

        threading.Thread(target=create_raven_project_api, daemon=True).start()
        self.window.destroy()

class NewColonyMenu:
    def __init__(self, parent_frame):
        self.window = tk.Toplevel(parent_frame)
        self.window.title(f"Initialize New Colony - {current_system.get('name', 'Unknown')}")
        self.window.geometry("400x420")
        self.window.attributes("-topmost", True)
        self.window.grab_set()

        try:
            current_station = ""
            current_market_id = 0
            target_body = ""
            station_type = ""

            if monitor and getattr(monitor, 'state', None):
                raw_station = monitor.state.get("StationName")
                current_station = str(raw_station) if raw_station else ""

                raw_market = monitor.state.get("MarketID")
                current_market_id = raw_market if raw_market else 0

                raw_body = monitor.state.get("BodyName")
                if not raw_body: raw_body = monitor.state.get("Body")

                target_body = str(raw_body) if raw_body else ""
                sys_name = current_system.get("name", "")

                if sys_name and target_body.startswith(sys_name): target_body = target_body[len(sys_name):].strip()
                elif target_body == sys_name: target_body = ""

                raw_type = monitor.state.get("StationType")
                raw_type_str = str(raw_type) if raw_type else ""

                if "Coriolis" in raw_type_str: station_type = "Coriolis Starport"
                elif "Outpost" in raw_type_str: station_type = "Outpost"
                elif "Asteroid" in raw_type_str: station_type = "Asteroid Base"
                elif "Orbis" in raw_type_str: station_type = "Orbis Starport"
                elif "Ocellus" in raw_type_str: station_type = "Ocellus Starport"

            if not current_station and last_docked_station.get("name"): current_station = str(last_docked_station["name"])
            if not current_market_id and last_docked_station.get("market_id"): current_market_id = last_docked_station["market_id"]
            current_station = clean_station_name(current_station)

            tk.Label(self.window, text="Station / Build Name:").pack(pady=(10, 2))
            self.name_entry = tk.Entry(self.window, width=40)
            self.name_entry.insert(0, current_station)
            self.name_entry.pack()

            tk.Label(self.window, text="Target Body (e.g., A 1 a):").pack(pady=(10, 2))
            self.body_entry = tk.Entry(self.window, width=40)
            self.body_entry.insert(0, target_body)
            self.body_entry.pack()

            tk.Label(self.window, text="Build Type:").pack(pady=(10, 2))
            self.type_combo = ttk.Combobox(self.window, values=list(BUILD_TYPES_MAP.keys()), state="readonly", width=37)
            keys = list(BUILD_TYPES_MAP.keys())
            if station_type and station_type in keys: self.type_combo.current(keys.index(station_type))
            elif keys: self.type_combo.current(0)
            self.type_combo.pack()

            tk.Label(self.window, text="Market ID (Auto-filled if docked):", fg="#aaaaaa").pack(pady=(10, 2))
            self.market_id_var = tk.StringVar(self.window, value=str(current_market_id))
            tk.Entry(self.window, textvariable=self.market_id_var, width=25, justify="center").pack(pady=(0, 5))

            self.browser_var = tk.BooleanVar(self.window, value=True)
            tk.Checkbutton(self.window, text="Auto-open project in browser", variable=self.browser_var).pack(pady=(5, 0))

            self.bypass_var = tk.BooleanVar(self.window, value=False)
            tk.Checkbutton(self.window, text="Manual Commodity Entry (Bypass Live Sync)", variable=self.bypass_var, fg="#ff7700").pack(pady=(0, 5))

            btn_frame = tk.Frame(self.window)
            btn_frame.pack(pady=10)
            tk.Button(btn_frame, text="Deploy Colony", command=self.start_project).pack(side=tk.LEFT, padx=10)
            tk.Button(btn_frame, text="Cancel", command=self.window.destroy).pack(side=tk.LEFT, padx=10)

        except Exception as e:
            log_error(f"UI Crash in NewColonyMenu: {traceback.format_exc()}")
            tk.Label(self.window, text="UI Initialization Failed: Check Plugin Debug Log", fg="#ff4444", font=("Arial", 10, "bold")).pack(pady=20)

    def start_project(self):
        global active_project
        if current_system['name'] == "Unknown":
            self.window.destroy()
            return

        name = clean_station_name(self.name_entry.get().strip() or "Unnamed Port")
        target_body = self.body_entry.get().strip()
        selected_display = self.type_combo.get()
        actual_build_type = BUILD_TYPES_MAP.get(selected_display, selected_display)

        manual_id_str = self.market_id_var.get().strip()
        market_id = int(manual_id_str) if manual_id_str.isdigit() else 0
        if market_id == 0: market_id = resolve_market_id(name)

        active_project.update({
            "is_active": True,
            "name": name,
            "target_body": target_body,
            "build_type": actual_build_type,
            "system_site_id": None,
            "market_id": market_id,
            "build_id": None,
            "force_bypass": False,
            "manual_cargo_dict": {},
            "auto_open_browser": self.browser_var.get(),
            "progress_data": BUILD_CARGO_MAP.get(str(actual_build_type).lower(), {}).copy()
        })

        if self.bypass_var.get():
            base_cargo = BUILD_CARGO_MAP.get(str(actual_build_type).lower(), {}).copy()
            ManualEntryMenu(self.window.master, base_cargo, name)
            self.window.destroy()
            return

        threading.Thread(target=create_raven_project_api, daemon=True).start()
        self.window.destroy()

# -------------------------------------------------------------------------
# BACKGROUND WORKERS & PARSERS
# -------------------------------------------------------------------------
def read_market_json():
    paths_to_check = []
    manual_path = config.get_str("RCC_JournalPath")
    if manual_path:
        paths_to_check.append(os.path.join(manual_path, 'Market.json'))
        paths_to_check.append(manual_path)

    try:
        jdir = config.get_str('journaldir')
        if jdir: paths_to_check.extend([os.path.join(jdir, 'Market.json'), os.path.abspath(os.path.join(jdir, 'Market.json'))])
    except: pass

    if monitor and getattr(monitor, 'monitor', None):
        try:
            mjdir = getattr(monitor.monitor, 'journaldir', None)
            if mjdir: paths_to_check.append(os.path.join(mjdir, 'Market.json'))
        except: pass

    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                saved_games = winreg.QueryValueEx(key, "{4C5C32FF-BB9D-43b0-B5B4-2D72E54EAAA4}")[0]
                paths_to_check.append(os.path.join(saved_games, "Frontier Developments", "Elite Dangerous", "Market.json"))
        except: pass
        paths_to_check.append(os.path.join(os.path.expanduser('~'), "Saved Games", "Frontier Developments", "Elite Dangerous", "Market.json"))

    if os.name == 'posix':
        paths_to_check.extend([
            os.path.expanduser("~/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous/Market.json"),
            os.path.expanduser("~/Saved Games/Frontier Developments/Elite Dangerous/Market.json"),
            os.path.expanduser("~/.var/app/io.edcd.EDMarketConnector/data/EDMarketConnector/journals/Market.json")
        ])

    checked = set()
    for p in paths_to_check:
        if not p or p in checked: continue
        checked.add(p)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f: return json.load(f)
            except Exception as e: log_error(f"Failed to read {p}: {e}")

    log_error("Could not locate Market.json on disk anywhere.")
    return None

def parse_market_data(market_data):
    global active_project, latest_market_data
    try:
        m_id = market_data.get("id") or market_data.get("MarketID")
        if not m_id: return
        m_id = int(m_id)
        live_demands = {}
        items = market_data.get("items") or market_data.get("Items") or []

        for item in items:
            demand = item.get("demand") if item.get("demand") is not None else item.get("Demand", 0)
            name = item.get("name") or item.get("Name", "")
            if demand > 0:
                name = name.lower().strip()
                if name.startswith('$'): name = name.replace('$', '').replace('_name;', '').strip()
                live_demands[name] = demand

        if live_demands:
            latest_market_data["market_id"] = m_id
            latest_market_data["demands"] = live_demands

            if active_project.get("is_active") and active_project.get("market_id") == m_id:
                active_project["progress_data"] = live_demands
                if config.get_str("RCC_HUDShowAllProjects") != "1" and hud_instance:
                    hud_instance.update_progress([{"title": None, "demands": live_demands}], force_show=True)

                build_id = active_project.get("build_id")
                if build_id and not active_project.get("force_bypass"):
                    threading.Thread(target=sync_live_market_to_server, args=(build_id, live_demands), daemon=True).start()

    except Exception as e: log_error(f"Live Market Parse Error: {e}")

def project_progress_loop():
    global current_system
    while True:
        try:
            if monitor and getattr(monitor, 'state', None):
                if current_system["name"] == "Unknown":
                    sys_name = monitor.state.get("SystemName")
                    if sys_name and sys_name != "Unknown":
                        set_current_system(sys_name, monitor.state.get("SystemAddress", 0), monitor.state.get("StarPos", [0.0, 0.0, 0.0]))
                m_id = monitor.state.get("MarketID")
                s_name = monitor.state.get("StationName")
                if m_id and s_name and str(m_id) != "0":
                    try:
                        m_id_int = int(m_id)
                        if last_docked_station["market_id"] != m_id_int: set_last_docked(s_name, m_id_int)
                    except ValueError: pass
            fetch_project_progress()
        except Exception as e:
            log_error(f"Error in project_progress_loop: {e}")
        time.sleep(5)

def fetch_project_progress():
    if config.get_str("RCC_HUDShowAllProjects") == "1" and current_system['name'] != "Unknown":
        try:
            url = f"{RCC_API_BASE}/api/v2/system/{urllib.parse.quote(current_system['name'])}/sites"
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                sites = resp.json()
                build_sites = [s for s in sites if s.get("status") == "build" and s.get("buildId")]
                projects_render_data = []
                for s in build_sites:
                    b_id = s.get("buildId")
                    p_resp = session.get(f"{RCC_API_BASE}/api/project/{b_id}", timeout=10)
                    if p_resp.status_code == 200:
                        comms = p_resp.json().get("commodities", {})
                        if active_project.get("is_active") and active_project.get("build_id") == b_id:
                            active_project["progress_data"] = comms
                        btype = s.get("buildType", "")
                        display_type = {v: k for k, v in BUILD_TYPES_MAP.items()}.get(btype, btype)
                        clean_name = clean_station_name(s.get("name", "Unknown"))
                        projects_render_data.append({"title": f"{display_type}: {clean_name}", "demands": comms})
                if hud_instance: hud_instance.update_progress(projects_render_data)
                return
        except Exception: pass

    build_id = active_project.get("build_id")
    if build_id:
        try:
            resp = session.get(f"{RCC_API_BASE}/api/project/{build_id}", timeout=10)
            if resp.status_code == 200:
                comms = resp.json().get("commodities", {})
                if comms is not None:
                    active_project["progress_data"] = comms
                    if hud_instance: hud_instance.update_progress([{"title": None, "demands": comms}])
        except Exception: pass

def sync_live_market_to_server(build_id, live_demands):
    api_key = config.get_str("RCC_ApiKey")
    if not api_key or not build_id: return
    payload = {"buildId": build_id, "commodities": live_demands}
    headers = {"rcc-key": api_key, "rcc-cmdr": get_cmdr_name(), "Content-Type": "application/json"}
    try: session.post(f"{RCC_API_BASE}/api/project/{urllib.parse.quote(build_id)}", json=payload, headers=headers, timeout=10)
    except Exception as e: log_error(f"Live Market Sync Error: {e}")

def trigger_system_update(sys_name):
    if hud_instance: hud_instance.update_system(sys_name, force_show=True)
    threading.Thread(target=fetch_edsm_data, args=(sys_name,), daemon=True).start()

def trigger_error_popup(title, msg):
    if not hud_instance: return
    def show_popup():
        top = tk.Toplevel()
        top.title(title)
        top.geometry("450x300")
        top.attributes("-topmost", True)
        top.grab_set()
        text_widget = tk.Text(top, wrap=tk.WORD, bg="#ffdddd", fg="black", relief=tk.FLAT)
        text_widget.insert(tk.END, msg)
        text_widget.config(state=tk.DISABLED)
        text_widget.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        tk.Button(top, text="Acknowledge", command=top.destroy).pack(pady=10)
    hud_instance.safe_execute(show_popup)

def fetch_and_display_jump(system_name, s_class, jumps_remaining):
    """Fetches EDSM data and updates the HUD jump target info."""
    if not system_name or system_name == "Unknown": return

    # Check if we already fetched and cached this exactly to avoid EDSM spam
    if active_route_target.get('last_fetched_sys') == system_name:
        if active_route_target.get('last_info_str') and hud_instance and config.get_str("RCC_HUDShowJump") != "0":
            hud_instance.safe_execute(lambda: hud_instance.jump_var.set(active_route_target['last_info_str']))
            hud_instance.show_hud()
        return

    try:
        url = f"https://www.edsm.net/api-v1/system?systemName={urllib.parse.quote(system_name)}&showInformation=1"
        resp = session.get(url, timeout=5)
        alleg = "Uninhabited"
        pop = 0
        faction = "None"

        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, dict) and data.get('information'):
                info = data['information']
                alleg = info.get('allegiance', 'Uninhabited')
                pop = info.get('population', 0)
                faction = info.get('faction', 'None')
                if isinstance(faction, dict):
                    faction = faction.get('name', 'None')
                if not faction: faction = "None"
                if not alleg: alleg = "Uninhabited"

        info_str = f"Target Locked: {system_name} (Class {s_class})"
        if jumps_remaining > 0: info_str += f" | {jumps_remaining} Jumps Left"

        if pop > 0: info_str += f"\nPop: {pop:,} | {alleg} | Faction: {faction}"
        else: info_str += f"\nUninhabited"

        active_route_target['last_fetched_sys'] = system_name
        active_route_target['last_info_str'] = info_str

        if hud_instance and config.get_str("RCC_HUDShowJump") != "0":
            hud_instance.safe_execute(lambda: hud_instance.jump_var.set(info_str))
            hud_instance.show_hud()

    except Exception as e:
        log_error(f"Jump Fetch Error: {e}")

# -------------------------------------------------------------------------
# EDMC LIFECYCLE HOOKS
# -------------------------------------------------------------------------
hud_instance = None
api_key_var = None
cmdr_name_var = None
hud_opacity_var = None
hud_bg_mode_var = None
hud_scale_var = None
hud_color_var = None
hud_hide_var = None
hud_columns_var = None
hud_align_var = None
hud_jump_var = None
hud_journal_path_var = None
hud_all_projects_var = None
hud_hide_tools_var = None
hud_hide_actions_var = None
hud_always_on_top_var = None

def plugin_prefs(parent, cmdr, is_beta):
    try:
        global api_key_var, cmdr_name_var, hud_opacity_var, hud_bg_mode_var, hud_scale_var, hud_color_var, hud_hide_var, hud_columns_var, hud_align_var, hud_jump_var, hud_journal_path_var, hud_all_projects_var, hud_hide_tools_var, hud_hide_actions_var, hud_always_on_top_var
        frame = nb.Frame(parent)

        api_key_var = tk.StringVar(value=config.get_str("RCC_ApiKey") or "")
        cmdr_name_var = tk.StringVar(value=config.get_str("RCC_CmdrName") or "")
        hud_color_var = tk.StringVar(value=config.get_str("RCC_HUDColor") or "Orange")
        hud_hide_var = tk.StringVar(value=config.get_str("RCC_HUDAutoHide") or "0")
        hud_columns_var = tk.StringVar(value=config.get_str("RCC_HUDColumns") or "Auto")
        hud_align_var = tk.StringVar(value=config.get_str("RCC_HUDAlign") or "Left")
        hud_journal_path_var = tk.StringVar(value=config.get_str("RCC_JournalPath") or "")
        hud_bg_mode_var = tk.StringVar(value=config.get_str("RCC_HUDBgMode") or "Transparent")

        hud_jump_var = tk.IntVar(value=0 if config.get_str("RCC_HUDShowJump") == "0" else 1)
        hud_all_projects_var = tk.IntVar(value=1 if config.get_str("RCC_HUDShowAllProjects") == "1" else 0)
        hud_hide_tools_var = tk.IntVar(value=1 if config.get_str("RCC_HideTools") == "1" else 0)
        hud_hide_actions_var = tk.IntVar(value=1 if config.get_str("RCC_HideActions") == "1" else 0)
        hud_always_on_top_var = tk.IntVar(value=0 if config.get_str("RCC_HUDAlwaysOnTop") == "0" else 1)

        try: op_val = float(config.get_str("RCC_HUDOpacity") or "1.0")
        except ValueError: op_val = 1.0
        hud_opacity_var = tk.DoubleVar(value=op_val)

        try: sc_val = int(config.get_str("RCC_HUDScale") or "100")
        except ValueError: sc_val = 100
        hud_scale_var = tk.IntVar(value=sc_val)

        tk.Label(frame, text="Raven Colonial API Key:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Entry(frame, textvariable=api_key_var, width=50).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)

        tk.Label(frame, text="Commander Name:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Entry(frame, textvariable=cmdr_name_var, width=50).grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)

        tk.Label(frame, text="HUD Text Color:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Combobox(frame, textvariable=hud_color_var, values=["Orange", "Green", "Cyan", "White"], state="readonly").grid(row=2, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="HUD Background Style:").grid(row=3, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Combobox(frame, textvariable=hud_bg_mode_var, values=["Transparent", "Solid Black"], state="readonly").grid(row=3, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="HUD Master Opacity:").grid(row=4, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Scale(frame, variable=hud_opacity_var, from_=0.1, to=1.0, resolution=0.05, orient=tk.HORIZONTAL).grid(row=4, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="HUD Layout Columns:").grid(row=5, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Combobox(frame, textvariable=hud_columns_var, values=["Auto", "1 Column", "2 Columns"], state="readonly").grid(row=5, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="HUD Scale (%):").grid(row=6, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Scale(frame, variable=hud_scale_var, from_=25, to=300, resolution=5, orient=tk.HORIZONTAL).grid(row=6, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="Auto-Hide HUD (Seconds, 0 = Off):").grid(row=7, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Entry(frame, textvariable=hud_hide_var, width=10).grid(row=7, column=1, sticky=tk.W, padx=10, pady=5)

        tk.Label(frame, text="HUD Text Alignment:").grid(row=8, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Combobox(frame, textvariable=hud_align_var, values=["Left", "Center", "Right"], state="readonly").grid(row=8, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="Show Jump Info on HUD:").grid(row=9, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Checkbutton(frame, variable=hud_jump_var).grid(row=9, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="Show ALL System Projects on HUD:").grid(row=10, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Checkbutton(frame, variable=hud_all_projects_var).grid(row=10, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="Manual Journal/Market.json Path:").grid(row=11, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Entry(frame, textvariable=hud_journal_path_var, width=50).grid(row=11, column=1, sticky=tk.W, padx=10, pady=5)

        tk.Label(frame, text="Hide Tools & Debug Tab:").grid(row=12, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Checkbutton(frame, variable=hud_hide_tools_var).grid(row=12, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="Hide Project Actions Tab:").grid(row=13, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Checkbutton(frame, variable=hud_hide_actions_var).grid(row=13, column=1, sticky=tk.W, padx=10)

        tk.Label(frame, text="HUD Always on Top:").grid(row=14, column=0, sticky=tk.W, padx=10, pady=5)
        tk.Checkbutton(frame, variable=hud_always_on_top_var).grid(row=14, column=1, sticky=tk.W, padx=10)

        return frame
    except Exception as e:
        log_error(f"Crash in plugin_prefs:\n{traceback.format_exc()}")
        show_edmc_error()
        err_frame = nb.Frame(parent)
        tk.Label(err_frame, text="Plugin Setup Error: Check debug log.", fg="red").pack()
        return err_frame

def prefs_changed(cmdr, is_beta):
    try:
        global tools_frame_ref, actions_frame_ref

        if api_key_var: config.set("RCC_ApiKey", api_key_var.get().strip())
        if cmdr_name_var: config.set("RCC_CmdrName", cmdr_name_var.get().strip())
        if hud_color_var: config.set("RCC_HUDColor", hud_color_var.get())
        if hud_columns_var: config.set("RCC_HUDColumns", hud_columns_var.get())
        if hud_opacity_var: config.set("RCC_HUDOpacity", str(hud_opacity_var.get()))
        if hud_bg_mode_var: config.set("RCC_HUDBgMode", str(hud_bg_mode_var.get()))
        if hud_scale_var: config.set("RCC_HUDScale", str(hud_scale_var.get()))
        if hud_hide_var: config.set("RCC_HUDAutoHide", hud_hide_var.get().strip())
        if hud_align_var: config.set("RCC_HUDAlign", hud_align_var.get())
        if hud_jump_var is not None: config.set("RCC_HUDShowJump", str(hud_jump_var.get()))
        if hud_all_projects_var is not None: config.set("RCC_HUDShowAllProjects", str(hud_all_projects_var.get()))
        if hud_journal_path_var: config.set("RCC_JournalPath", hud_journal_path_var.get().strip())
        if hud_hide_tools_var is not None: config.set("RCC_HideTools", str(hud_hide_tools_var.get()))
        if hud_hide_actions_var is not None: config.set("RCC_HideActions", str(hud_hide_actions_var.get()))
        if hud_always_on_top_var is not None: config.set("RCC_HUDAlwaysOnTop", str(hud_always_on_top_var.get()))

        if actions_frame_ref: actions_frame_ref.pack_forget()
        if tools_frame_ref: tools_frame_ref.pack_forget()

        if actions_frame_ref and config.get_str("RCC_HideActions") != "1":
            actions_frame_ref.pack(fill=tk.X, padx=5, pady=5)

        if tools_frame_ref and config.get_str("RCC_HideTools") != "1":
            tools_frame_ref.pack(fill=tk.X, padx=5, pady=5)

        if hud_instance:
            hud_instance.apply_settings()
            threading.Thread(target=fetch_project_progress, daemon=True).start()
    except Exception as e:
        log_error(f"Crash in prefs_changed:\n{traceback.format_exc()}")
        show_edmc_error()

def plugin_start3(plugin_dir):
    try:
        global hud_instance
        log_info(f"--- {plugin_name} v{plugin_version} Starting ---")
        load_build_data(plugin_dir)
        hud_instance = OverlayHUD()
        threading.Thread(target=project_progress_loop, daemon=True).start()

        saved_name = config.get_str("RCC_SysName")
        if saved_name and saved_name != "Unknown":
            addr_str = config.get_str("RCC_SysAddr")
            addr = int(addr_str) if addr_str and addr_str.isdigit() else 0
            try:
                pos_x = float(config.get_str("RCC_SysPosX") or "0.0")
                pos_y = float(config.get_str("RCC_SysPosY") or "0.0")
                pos_z = float(config.get_str("RCC_SysPosZ") or "0.0")
            except ValueError: pos_x, pos_y, pos_z = 0.0, 0.0, 0.0
            set_current_system(saved_name, addr, [pos_x, pos_y, pos_z])

        ls_name = config.get_str("RCC_LastStationName")
        ls_mid = config.get_str("RCC_LastMarketID")
        if ls_name:
            try: m_id = int(ls_mid) if ls_mid else 0
            except ValueError: m_id = 0
            last_docked_station["name"] = ls_name
            last_docked_station["market_id"] = m_id

        restore_active_project()
        return plugin_name
    except Exception as e:
        log_error(f"Crash in plugin_start3:\n{traceback.format_exc()}")
        show_edmc_error()
        return plugin_name

def plugin_app(parent):
    global tools_frame_ref, actions_frame_ref, overlay_toggle_var, main_error_label
    try:
        frame = tk.Frame(parent)
        val_overlay = config.get_str("RCC_EnableOverlay")
        overlay_toggle_var = tk.IntVar(value=0 if val_overlay == "0" else 1)

        def on_overlay_toggle():
            config.set("RCC_EnableOverlay", str(overlay_toggle_var.get()))
            if hud_instance:
                if overlay_toggle_var.get() == 1: hud_instance.update_system(current_system['name'], force_show=True)
                else: hud_instance.hide_hud()

        cb_overlay = tk.Checkbutton(frame, text="Enable In-Game Overlay", variable=overlay_toggle_var, command=on_overlay_toggle)
        cb_overlay.pack(anchor=tk.W, padx=10, pady=5)

        actions_frame_ref = tk.LabelFrame(frame, text="Project Actions")
        btn_link = tk.Button(actions_frame_ref, text="Link Planned/Active Colony", command=lambda: LinkProjectMenu(frame))
        btn_link.pack(fill=tk.X, padx=10, pady=4)
        btn_new = tk.Button(actions_frame_ref, text="Initialize New Colony", command=lambda: NewColonyMenu(frame))
        btn_new.pack(fill=tk.X, padx=10, pady=4)

        if config.get_str("RCC_HideActions") != "1": actions_frame_ref.pack(fill=tk.X, padx=5, pady=5)

        tools_frame_ref = tk.LabelFrame(frame, text="Tools & Debug")

        btn_repo = tk.Button(tools_frame_ref, text="Toggle Overlay Reposition", command=lambda: hud_instance and hud_instance.toggle_reposition())
        btn_repo.pack(fill=tk.X, padx=10, pady=4)

        btn_unlink = tk.Button(tools_frame_ref, text="Unlink Current Project", command=unlink_project)
        btn_unlink.pack(fill=tk.X, padx=10, pady=4)

        btn_report = tk.Button(tools_frame_ref, text="System Colonial Report", command=lambda: ColonialReportMenu(frame))
        btn_report.pack(fill=tk.X, padx=10, pady=4)

        btn_debug = tk.Button(tools_frame_ref, text="View Plugin Debug Log", fg="#d35400", command=lambda: DebugLogMenu(frame))
        btn_debug.pack(fill=tk.X, padx=10, pady=4)

        if config.get_str("RCC_HideTools") != "1": tools_frame_ref.pack(fill=tk.X, padx=5, pady=5)

        main_error_label = tk.Label(frame, text="", fg="red")
        main_error_label.pack(fill=tk.X, padx=5, pady=2)

        return frame
    except Exception as e:
        log_error(f"Crash in plugin_app:\n{traceback.format_exc()}")
        err_frame = tk.Frame(parent)
        tk.Label(err_frame, text="Plugin Interface Error: Check debug log.", fg="red").pack()
        return err_frame

def plugin_stop():
    try:
        global hud_instance
        if hud_instance: hud_instance.destroy()
        session.close()
    except Exception as e:
        log_error(f"Crash in plugin_stop:\n{traceback.format_exc()}")

def cmdrs_data(data, is_beta):
    try:
        log_debug("cmdrs_data hook fired from EDMC CAPI.")
        market_data = data.get("market")
        if market_data: parse_market_data(market_data)
        else: log_debug("No 'market' key found in CAPI payload.")
    except Exception as e:
        log_error(f"Crash in cmdrs_data:\n{traceback.format_exc()}")
        show_edmc_error()

def journal_entry(cmdr, is_beta, system, station, entry, state):
    global current_system, active_project, system_scans_cache, last_docked_station, latest_market_data, active_route_target
    try:
        event = entry.get('event')
        if state and state.get('SystemName') and current_system['name'] != state.get('SystemName'):
            set_current_system(state.get('SystemName'), state.get('SystemAddress', 0), state.get('StarPos', [0.0, 0.0, 0.0]))
        if system and current_system['name'] != system:
            set_current_system(system, current_system['address'], current_system['pos'])

        if event == 'NavRouteClear':
            active_route_target['jumps_left'] = 0

        elif event == 'FSDTarget':
            # Pre-fetch and display data immediately so it's ready before charging
            active_route_target['system'] = entry.get('Name', '')
            active_route_target['jumps_left'] = entry.get('RemainingJumpsInRoute', 0)
            active_route_target['star_class'] = entry.get('StarClass', '')
            threading.Thread(target=fetch_and_display_jump, args=(active_route_target['system'], active_route_target['star_class'], active_route_target['jumps_left']), daemon=True).start()

        elif event == 'Music' and entry.get('MusicTrack') == 'FSDCharge':
            # Trigger HUD explicitly the moment the FSD actually begins charging
            sys_name = active_route_target.get('system')
            if sys_name:
                threading.Thread(target=fetch_and_display_jump, args=(sys_name, active_route_target.get('star_class', ''), active_route_target.get('jumps_left', 0)), daemon=True).start()

        elif event == 'StartJump' and entry.get('JumpType') == 'Hyperspace':
            # Fallback if audio was disabled or missed
            sys_name = entry.get('StarSystem', 'Unknown')
            star_class = entry.get('StarClass', 'Unknown')
            jumps = active_route_target.get('jumps_left', 0) if sys_name == active_route_target.get('system') else 0
            threading.Thread(target=fetch_and_display_jump, args=(sys_name, star_class, jumps), daemon=True).start()

        elif event == 'ColonisationConstructionDepot':
            m_id = entry.get('MarketID')
            if m_id:
                m_id = int(m_id)
                live_demands = {}
                for req in entry.get('ResourcesRequired', []):
                    name = req.get('Name', '').lower()
                    if name.startswith('$'): name = name.replace('$', '').replace('_name;', '').strip()
                    required = req.get('RequiredAmount', 0)
                    provided = req.get('ProvidedAmount', 0)
                    demand = required - provided
                    if demand > 0: live_demands[name] = demand

                if live_demands:
                    latest_market_data["market_id"] = m_id
                    latest_market_data["demands"] = live_demands

                    if active_project.get("is_active") and active_project.get("market_id") == m_id:
                        active_project["progress_data"] = live_demands
                        build_id = active_project.get("build_id")
                        if build_id and not active_project.get("force_bypass"):
                            threading.Thread(target=sync_live_market_to_server, args=(build_id, live_demands), daemon=True).start()

                    if config.get_str("RCC_HUDShowAllProjects") != "1" and active_project.get("is_active"):
                        if hud_instance: hud_instance.update_progress([{"title": None, "demands": live_demands}], force_show=True)

        elif event == 'Location':
            set_current_system(entry.get('StarSystem', 'Unknown System'), entry.get('SystemAddress', 0), entry.get('StarPos', [0.0, 0.0, 0.0]))
            system_scans_cache.clear()
            if entry.get('Docked'):
                m_id = entry.get('MarketID', 0)
                s_name = entry.get("StationName", "")
                set_last_docked(s_name, m_id)
                if active_project['is_active']:
                    c_docked, c_target = clean_station_name(s_name).lower(), clean_station_name(active_project['name']).lower()
                    if c_docked == c_target or c_docked in c_target or c_target in c_docked:
                        if active_project['market_id'] != m_id:
                            active_project['market_id'] = m_id
                            save_active_project()

        elif event == 'FSDJump':
            set_current_system(entry.get('StarSystem', 'Unknown System'), entry.get('SystemAddress', 0), entry.get('StarPos', [0.0, 0.0, 0.0]))
            system_scans_cache.clear()
            if config.get_str("RCC_HUDShowJump") != "0":
                econ = entry.get('SystemEconomy_Localised', entry.get('SystemEconomy', 'Unknown')).replace('Economy', '').replace('$economy_', '').strip()
                sec = entry.get('SystemSecurity_Localised', entry.get('SystemSecurity', 'Unknown')).replace('Security', '').replace('$SYSTEM_SECURITY_', '').strip()
                alleg = entry.get('SystemAllegiance', 'Unknown')
                pop = entry.get('Population', 0)

                jump_info = f"Arrived: {entry.get('StarSystem', 'Unknown System')}"
                if pop > 0: jump_info += f"\nPop: {pop:,} | {alleg} | {econ} | {sec}"
                else: jump_info += "\nUninhabited"

                if hud_instance:
                    hud_instance.safe_execute(lambda: hud_instance.jump_var.set(jump_info))
                    hud_instance.show_hud()
            else:
                if hud_instance: hud_instance.safe_execute(lambda: hud_instance.jump_var.set(""))

        elif event == 'FSSDiscoveryScan': system_scans_cache.clear()
        elif event == 'Scan':
            body_id = entry.get('BodyID')
            if body_id is not None:
                system_scans_cache[body_id] = {
                    "bodyId": body_id, "name": entry.get("BodyName", ""),
                    "type": "Star" if "StarType" in entry else "Planet",
                    "subType": entry.get("StarType", entry.get("PlanetClass", "")),
                    "distanceToArrival": entry.get("DistanceFromArrivalLS", 0.0),
                    "terraformingState": entry.get("TerraformState", ""),
                    "volcanismType": entry.get("Volcanism", ""),
                    "landable": entry.get("Landable", False)
                }

        elif event == 'FSSAllBodiesFound':
            system_address = entry.get('SystemAddress', current_system['address'])
            if system_scans_cache:
                threading.Thread(target=update_sys_bodies, args=(system_address, list(system_scans_cache.values())), daemon=True).start()

        elif event == 'Cargo':
            ship_name = state.get('ShipName', 'Unknown')
            ship_type = state.get('ShipType', 'Unknown')
            cargo_dict = {item['Name']: item['Count'] for item in entry.get('Inventory', [])}
            threading.Thread(target=publish_current_ship, args=(get_cmdr_name(), ship_name, ship_type, cargo_dict), daemon=True).start()

        elif event == 'MarketSell':
            if active_project['is_active'] and active_project.get('build_id'):
                m_id = entry.get('MarketID')
                if m_id and str(m_id) == str(active_project.get('market_id')):
                    commodity = entry.get('Type', '').lower()
                    if commodity.startswith('$'): commodity = commodity.replace('$', '').replace('_name;', '').strip()
                    threading.Thread(target=contribute_to_project, args=(active_project['build_id'], get_cmdr_name(), {commodity: entry.get('Count', 0)}), daemon=True).start()

        elif event in ['CarrierJump', 'CarrierBuy']:
            threading.Thread(target=publish_fleet_carrier, args=(get_cmdr_name(), entry.get('MarketID'), entry.get('CarrierName', 'Unknown Carrier'), entry.get('Callsign', 'XXX-XXX')), daemon=True).start()

        elif event == 'Docked':
            station_name = entry.get('StationName', '')
            m_id = entry.get('MarketID', 0)
            set_last_docked(station_name, m_id)
            if active_project['is_active']:
                c_docked, c_target = clean_station_name(station_name).lower(), clean_station_name(active_project['name']).lower()
                if c_docked == c_target or c_docked in c_target or c_target in c_docked:
                    if active_project['market_id'] != m_id:
                        active_project['market_id'] = m_id
                        save_active_project()

            if entry.get('StationType') == 'FleetCarrier':
                threading.Thread(target=publish_fleet_carrier, args=(get_cmdr_name(), m_id, station_name, "Docked-FC"), daemon=True).start()

            if hud_instance: hud_instance.show_hud()

    except Exception as e:
        log_error(f"Critical Journal Error processing event {entry.get('event', 'Unknown')}:\n{traceback.format_exc()}")
        show_edmc_error()

# -------------------------------------------------------------------------
# RAVEN COLONIAL API WRAPPERS
# -------------------------------------------------------------------------
def create_raven_project_api():
    site_id = active_project.get("system_site_id")
    cmdr_name = get_cmdr_name()
    api_key = config.get_str("RCC_ApiKey")
    if not api_key:
        trigger_error_popup("Configuration Error", "No RCC API Key found!\n\nPlease set your API key in EDMC Settings.")
        return

    market_id = int(active_project.get("market_id", 0))
    exact_name = None
    if market_id != 0:
        if monitor and getattr(monitor, 'state', None) and monitor.state.get("MarketID") == market_id: exact_name = monitor.state.get("StationName")
        elif last_docked_station["market_id"] == market_id: exact_name = last_docked_station["name"]
        else:
            for s_name, m_id in system_stations_cache.items():
                if m_id == market_id:
                    exact_name = s_name
                    break

    if exact_name:
        clean_exact = clean_station_name(exact_name)
        if clean_exact != active_project["name"]: active_project["name"] = clean_exact

    active_project["name"] = clean_station_name(active_project["name"])
    build_id = active_project.get("build_id")

    if build_id:
        headers = {"rcc-key": api_key, "rcc-cmdr": cmdr_name, "Content-Type": "application/json"}
        try:
            response = session.put(f"{RCC_API_BASE}/api/project/{urllib.parse.quote(build_id)}/link/{urllib.parse.quote(cmdr_name)}", headers=headers, timeout=10)
            if response.status_code in [200, 201, 204]:
                save_active_project()
                if latest_market_data["market_id"] == active_project["market_id"] and latest_market_data["demands"] and not active_project.get("force_bypass"):
                    active_project["progress_data"] = latest_market_data["demands"]
                    threading.Thread(target=sync_live_market_to_server, args=(build_id, latest_market_data["demands"]), daemon=True).start()
                if hud_instance:
                    hud_instance.update_status(f"Joined Project: {active_project['name']} ✓", force_show=True)
                    threading.Thread(target=fetch_project_progress, daemon=True).start()
                if active_project["auto_open_browser"]: webbrowser.open(f"{RCC_UX_BASE}/#build={urllib.parse.quote(build_id)}")
                return
            else:
                err_text = response.text.strip()
                trigger_error_popup("API Link Failed", f"Raven Colonial rejected joining the project:\n\n{err_text[:250]}")
                if hud_instance: hud_instance.update_status("Fail: Link Rejected", force_show=True)
                return
        except Exception as e:
            trigger_error_popup("Network Error", f"Failed to join existing project:\n\n{e}")
            return

    try:
        if current_system["address"] == 0 or current_system["name"] == "Unknown":
            trigger_error_popup("System Unknown", "System unregistered.\n\nPlease click the 'Update' button on the main EDMC window to force a location sync.")
            return

        btype = active_project["build_type"]
        cargo_dict = BUILD_CARGO_MAP.get(str(btype).lower(), {}).copy()
        has_live = False

        if market_id != 0 and latest_market_data["market_id"] == market_id and latest_market_data["demands"]: has_live = True

        if active_project.get("force_bypass") and active_project.get("manual_cargo_dict"):
            has_live = True
            cargo_dict = active_project["manual_cargo_dict"].copy()

        if has_live:
            if not active_project.get("force_bypass"): cargo_dict = latest_market_data["demands"].copy()
        else:
            trigger_error_popup("Missing Live Market Data", "To capture the exact commodity requirements, you MUST physically dock and view the market board in-game BEFORE linking a new planned colony.")
            if hud_instance: hud_instance.update_status("Fail: Open Market First", force_show=True)
            return

        max_need = sum(cargo_dict.values()) if cargo_dict else 1

        raw_body = str(active_project["target_body"]).strip()
        body_name_str = raw_body if raw_body else current_system['name']
        b_num = int(raw_body) if raw_body.isdigit() else 0

        payload = {
            "buildType": str(btype), "buildName": str(active_project["name"]), "marketId": int(active_project.get("market_id", 0)),
            "systemAddress": int(current_system["address"]), "systemName": str(current_system["name"]),
            "starPos": [float(p) for p in current_system.get("pos", [0.0, 0.0, 0.0])],
            "architectName": cmdr_name, "maxNeed": int(max_need), "commodities": cargo_dict,
            "bodyName": body_name_str, "bodyNum": b_num if b_num >= 0 else 0, "isPrimaryPort": False if site_id else True
        }

        if site_id: payload["systemSiteId"] = str(site_id)
        headers = {"rcc-key": api_key, "rcc-cmdr": cmdr_name, "Content-Type": "application/json"}

        response = session.put(f"{RCC_API_BASE}/api/project/", json=payload, headers=headers, timeout=10)
        if response.status_code in [200, 201]:
            response_data = response.json()
            build_id = response_data.get("buildId", "")
            active_project["build_id"] = build_id
            save_active_project()

            if hud_instance:
                hud_instance.update_status(f"Project Active: {active_project['name']} ✓", force_show=True)
                threading.Thread(target=fetch_project_progress, daemon=True).start()

            if build_id and site_id:
                update_payload = {"update": [{"id": str(site_id), "name": str(active_project["name"]), "bodyNum": b_num if b_num >= 0 else 0, "bodyName": body_name_str, "buildType": str(btype), "buildId": str(build_id), "status": "build"}], "delete": [], "architect": cmdr_name}
                session.put(f"{RCC_API_BASE}/api/v2/system/{urllib.parse.quote(current_system['name'])}/sites", json=update_payload, headers=headers, timeout=10)

            if active_project["auto_open_browser"]:
                if build_id: webbrowser.open(f"{RCC_UX_BASE}/#build={urllib.parse.quote(build_id)}")
                else: webbrowser.open(f"{RCC_UX_BASE}/#sys={urllib.parse.quote(current_system['name'])}")
        else:
            trigger_error_popup("API Link Failed", f"Raven Colonial rejected the project creation:\n\n{response.text[:250]}")
            if hud_instance: hud_instance.update_status("Fail: Creation Rejected", force_show=True)

    except requests.exceptions.RequestException as e:
        trigger_error_popup("Network Error", f"Could not connect to Raven Colonial:\n\n{e}")
        if hud_instance: hud_instance.update_status("Raven Colonial: Network Error ✗", force_show=True)
    except Exception as e:
        trigger_error_popup("Script Crash", f"An error occurred during linking:\n\n{e}")

def publish_current_ship(cmdr_name, ship_name, ship_type, cargo_dict):
    api_key = config.get_str("RCC_ApiKey")
    if not api_key: return
    max_cargo = sum(cargo_dict.values()) if cargo_dict else 100
    try: session.post(f"{RCC_API_BASE}/api/cmdr/currentShip", json={"cmdr": get_cmdr_name(), "name": ship_name, "type": ship_type, "maxCargo": max_cargo, "cargo": cargo_dict}, headers={"rcc-key": api_key, "Content-Type": "application/json"}, timeout=10)
    except Exception as e: log_error(f"Ship Sync Error: {e}")

def contribute_to_project(build_id, cmdr_name, cargo_diff):
    if not cargo_diff: return
    try:
        resp = session.post(f"{RCC_API_BASE}/api/project/{urllib.parse.quote(build_id)}/contribute/{urllib.parse.quote(get_cmdr_name())}", json=cargo_diff, headers={"Content-Type": "application/json", "rcc-key": config.get_str("RCC_ApiKey")}, timeout=10)
        if resp.status_code in [200, 201, 204]: threading.Thread(target=fetch_project_progress, daemon=True).start()
    except Exception as e: log_error(f"Contribution Error: {e}")

def publish_fleet_carrier(cmdr_name, market_id, name, callsign):
    if not config.get_str("RCC_ApiKey"): return
    try: session.put(f"{RCC_API_BASE}/api/fc/{market_id}", json={"marketId": market_id, "name": callsign, "displayName": name, "cargo": None}, headers={"rcc-key": config.get_str("RCC_ApiKey"), "rcc-cmdr": get_cmdr_name(), "Content-Type": "application/json"}, timeout=10)
    except Exception as e: log_error(f"FC Sync Error: {e}")

def update_sys_bodies(address, bods):
    if not config.get_str("RCC_ApiKey") or not bods: return
    try: session.put(f"{RCC_API_BASE}/api/v2/system/{address}/bodies", json=bods, headers={"rcc-key": config.get_str("RCC_ApiKey"), "Content-Type": "application/json"}, timeout=15)
    except Exception as e: log_error(f"System Bodies Sync Error: {e}")

def fetch_edsm_data(system_name):
    global system_colonial_report, system_stations_cache
    system_colonial_report = []
    try:
        resp_stations = session.get(f"https://www.edsm.net/api-system-v1/stations?systemName={urllib.parse.quote(system_name)}", timeout=10)
        system_stations_cache.clear()
        if resp_stations.status_code == 200:
            data_stations = resp_stations.json()
            if isinstance(data_stations, dict) and 'stations' in data_stations:
                for st in data_stations.get('stations', []):
                    if 'name' in st and 'marketId' in st: system_stations_cache[st['name']] = st['marketId']

        resp_bodies = session.get(f"https://www.edsm.net/api-system-v1/bodies?systemName={urllib.parse.quote(system_name)}", timeout=10)
        if resp_bodies.status_code == 200:
            data_bodies = resp_bodies.json()
            if not isinstance(data_bodies, dict) or not data_bodies.get('bodies'):
                if hud_instance: hud_instance.update_signals("No EDSM body data found.", force_show=True)
                return

            bio_count = geo_count = interesting_count = 0
            for body in data_bodies.get('bodies', []):
                if 'signals' in body:
                    bio_count += body['signals'].get('Biological', 0)
                    geo_count += body['signals'].get('Geological', 0)
                name = body.get('name', '').replace(system_name, '').strip()
                subType = body.get('subType', '')
                is_interesting, reasons = False, []

                if subType in ['Earthlike body', 'Water world', 'Ammonia world']: is_interesting = True
                if body.get('terraformingState') in ['Terraformable', 'Terraforming', 'Terraformed']: is_interesting, reasons = True, reasons + ["Terraformable"]
                if body.get('type') == 'Star' and subType in ['Black hole', 'Neutron Star', 'White Dwarf']: is_interesting = True

                signals = body.get('signals', {})
                bio, geo = signals.get('Biological', 0), signals.get('Geological', 0)
                if bio > 0: is_interesting, reasons = True, reasons + [f"{bio} Bio"]
                if geo > 0 or body.get('volcanismType'): is_interesting, reasons = True, reasons + [f"{geo} Geo" if geo > 0 else "Volcanism"]
                if body.get('rings'): is_interesting, reasons = True, reasons + ["Rings"]

                if is_interesting:
                    interesting_count += 1
                    system_colonial_report.append({"name": name or "Main Star", "tag": subType + (f" ({', '.join(reasons)})" if reasons else ""), "buffs": get_colonial_buffs(body)})

            if hud_instance: hud_instance.update_signals(f"Prime Targets: {interesting_count} | Bio: {bio_count} | Geo: {geo_count}", force_show=True)
    except Exception as e:
        logger.error(f"[{plugin_name}] EDSM Parse Error: {e}")
