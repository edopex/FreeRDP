#!/usr/bin/env python3
"""
FreeRDP Launcher — GTK4/libadwaita front-end for the custom sdl-freerdp build:
connection profiles, a clickable preview of the local monitors to choose which
ones the session spans, and colours that follow the active Omarchy theme.

Requires: python-gobject, libadwaita (GTK4)
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tomllib
import traceback
from dataclasses import dataclass
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, PangoCairo
except (ImportError, ValueError) as e:
    print(f"Error: missing dependency ({e}).\n"
          "Install with: sudo pacman -S python-gobject libadwaita", file=sys.stderr)
    sys.exit(1)

APP_ID = "dev.edopex.RdpLauncher"
VERSION = "2.0"

CONFIG_DIR = Path.home() / ".config/freerdp"
PROFILES_FILE = CONFIG_DIR / "profiles.json"
LOG_FILE = CONFIG_DIR / "last_connection.log"
DEFAULT_BINARY = "/home/edopex/Projects/FreeRDP/build/client/SDL/SDL3/sdl-freerdp"
FALLBACK_BINARY = "/usr/bin/sdl-freerdp3"
BIN_LINK = Path.home() / ".local/bin/rdp-launcher"
DESKTOP_FILE = Path.home() / ".local/share/applications/freerdp-launcher.desktop"

THEME_POLL_SECONDS = 2
STARTUP_GRACE_MS = 3000        # an exit before this counts as a failed connection

DEFAULTS = {
    "host": "", "port": "3389", "user": "", "pass": "", "domain": "",
    "multimon": True, "fullscreen": True, "dyn_res": True,
    "audio": True, "microphone": False, "camera": False, "clipboard": True,
    "gfx": False, "ignore_cert": True, "security": "auto",
    # Output names (e.g. "HDMI-A-1") left out of /multimon. None = default:
    # the HDMI TV, which stays "enabled" with DPMS off, so FreeRDP sees it.
    "excluded_monitors": None,
}

# "auto" lets FreeRDP negotiate (NLA/TLS/RDP). Some servers reject the
# negotiation with SSL_NOT_ALLOWED_BY_SERVER and need the level forced.
SECURITY = [("auto", "Automática"), ("nla", "NLA"), ("tls", "TLS"), ("rdp", "RDP")]

FRIENDLY_ERRORS = {
    "ERRCONNECT_CONNECT_FAILED": "No se pudo llegar al servidor. Revisa el host, el puerto y la red.",
    "ERRCONNECT_DNS_NAME_NOT_FOUND": "No se encontró el nombre del host.",
    "ERRCONNECT_LOGON_FAILURE": "Usuario o contraseña incorrectos.",
    "ERRCONNECT_AUTHENTICATION_FAILED": "Falló la autenticación: revisa usuario, contraseña y dominio.",
    "ERRCONNECT_PASSWORD_EXPIRED": "La contraseña expiró.",
    "ERRCONNECT_ACCOUNT_LOCKED_OUT": "La cuenta está bloqueada.",
    "ERRCONNECT_TLS_CONNECT_FAILED": "Falló la conexión TLS. Prueba otro nivel de seguridad.",
    "SSL_NOT_ALLOWED_BY_SERVER": "El servidor no acepta TLS: prueba Seguridad → RDP.",
    "HYBRID_REQUIRED_BY_SERVER": "El servidor exige NLA: prueba Seguridad → NLA.",
    "ERRCONNECT_CONNECT_CANCELLED": "La conexión se canceló.",
}


# ── Profiles ─────────────────────────────────────────────────────────────
def obfuscate_password(password: str) -> str:
    if not password:
        return ""
    return "b64:" + base64.b64encode(password.encode()).decode()


def deobfuscate_password(value: str) -> str:
    if value and value.startswith("b64:"):
        try:
            return base64.b64decode(value[4:].encode(), validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            return value
    return value or ""


def load_profiles() -> dict[str, dict]:
    try:
        data = json.loads(PROFILES_FILE.read_text())
    except (OSError, ValueError):
        return {}
    profiles = {}
    for name, entry in data.items():
        profile = {**DEFAULTS, **entry}
        profile["pass"] = deobfuscate_password(profile.get("pass", ""))
        profiles[name] = profile
    return profiles


def save_profiles(profiles: dict[str, dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {name: {**p, "pass": obfuscate_password(p.get("pass", ""))}
            for name, p in profiles.items()}
    tmp = PROFILES_FILE.with_name(f".{PROFILES_FILE.name}.tmp")
    tmp.write_text(json.dumps(data, indent=4))
    tmp.replace(PROFILES_FILE)


# ── Monitors ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Monitor:
    name: str           # output name, e.g. "DP-1"
    description: str
    width: int          # pixels, rotation applied
    height: int
    x: float            # logical layout position
    y: float
    scale: float = 1.0

    @property
    def logical(self) -> tuple[float, float]:
        return self.width / self.scale, self.height / self.scale

    @property
    def is_tv(self) -> bool:
        return "hdmi" in self.name.lower()


def detect_monitors() -> list[Monitor]:
    """Local layout from Hyprland (instant, no windows flashing on screen)."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True,
                             text=True, timeout=3, check=True).stdout
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    monitors = []
    for d in data:
        if d.get("disabled") or d.get("mirrorOf", "none") not in ("none", "", None):
            continue
        w, h = int(d["width"]), int(d["height"])
        if int(d.get("transform", 0)) % 2 == 1:      # 90°/270°: portrait
            w, h = h, w
        monitors.append(Monitor(d["name"], d.get("description", ""), w, h,
                                float(d.get("x", 0)), float(d.get("y", 0)),
                                float(d.get("scale", 1.0)) or 1.0))
    return sorted(monitors, key=lambda m: (m.x, m.y))


_SDL_MONITOR = re.compile(r"\[(\d+)\]\s*\[([^\]]*)\]")


def sdl_monitor_ids(binary: str) -> dict[str, int]:
    """Output name → SDL display ID, as `/monitors:` expects (IDs change on hotplug)."""
    try:
        out = subprocess.run([binary, "/list:monitor"], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {}
    ids = {}
    for match in _SDL_MONITOR.finditer(out.stdout + out.stderr):
        names = re.findall(r"\(([^()]+)\)", match.group(2))
        if names:
            ids[names[-1]] = int(match.group(1))
    return ids


def layout_bbox(monitors: list[Monitor]) -> tuple[float, float, float, float]:
    min_x = min(m.x for m in monitors)
    min_y = min(m.y for m in monitors)
    max_x = max(m.x + m.logical[0] for m in monitors)
    max_y = max(m.y + m.logical[1] for m in monitors)
    return min_x, min_y, max_x - min_x, max_y - min_y


def touches(a: Monitor, b: Monitor) -> bool:
    """Share an edge (not just a corner), so the pointer can cross."""
    (aw, ah), (bw, bh) = a.logical, b.logical
    side = (a.x + aw == b.x or b.x + bw == a.x) and a.y < b.y + bh and b.y < a.y + ah
    stack = (a.y + ah == b.y or b.y + bh == a.y) and a.x < b.x + bw and b.x < a.x + aw
    return side or stack


def primary_of(monitors: list[Monitor]) -> Monitor | None:
    """The monitor at the origin: FreeRDP makes it the session's main screen."""
    return next((m for m in monitors if m.x == 0 and m.y == 0),
                monitors[0] if monitors else None)


def find_binary() -> str | None:
    for path in (DEFAULT_BINARY, FALLBACK_BINARY):
        if os.access(path, os.X_OK):
            return path
    return shutil.which("sdl-freerdp3") or shutil.which("sdl-freerdp")


# ── Omarchy theme ────────────────────────────────────────────────────────
COLORS_FILE = Path.home() / ".config/omarchy/current/theme/colors.toml"
_FALLBACK_COLORS = {"background": "#0f172a", "foreground": "#e2e8f0", "accent": "#3b82f6",
                    "color1": "#ef4444", "color2": "#10b981", "color3": "#f59e0b"}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: str, b: str, t: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(x + (y - x) * t))):02x}"
                         for x, y in zip(_rgb(a), _rgb(b)))


def _luminance(hex_color: str) -> float:
    r, g, b = (c / 255 for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def load_colors() -> dict[str, str]:
    try:
        data = tomllib.loads(COLORS_FILE.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    return {**_FALLBACK_COLORS, **{k: v for k, v in data.items() if isinstance(v, str)}}


def theme_signature() -> str:
    try:
        return COLORS_FILE.read_text()
    except OSError:
        return ""


def is_dark(colors: dict[str, str]) -> bool:
    return _luminance(colors["background"]) < 0.5


def on_color(colors: dict[str, str], bg: str) -> str:
    return colors["background"] if _luminance(bg) > 0.5 else "#ffffff"


def theme_css(colors: dict[str, str]) -> str:
    bg, fg, accent = colors["background"], colors["foreground"], colors["accent"]
    red, green, yellow = colors["color1"], colors["color2"], colors["color3"]
    tokens = {
        "accent-bg-color": accent,
        "accent-fg-color": on_color(colors, accent),
        "accent-color": _mix(accent, fg, 0.15) if is_dark(colors) else _mix(accent, bg, 0.2),
        "destructive-bg-color": red,
        "destructive-fg-color": on_color(colors, red),
        "destructive-color": red,
        "success-color": green,
        "warning-color": yellow,
        "error-color": red,
        "window-bg-color": bg,
        "window-fg-color": fg,
        "view-bg-color": _mix(bg, fg, 0.03),
        "view-fg-color": fg,
        "headerbar-bg-color": _mix(bg, fg, 0.05),
        "headerbar-fg-color": fg,
        "headerbar-backdrop-color": bg,
        "sidebar-bg-color": _mix(bg, fg, 0.05),
        "sidebar-fg-color": fg,
        "card-bg-color": _mix(bg, fg, 0.07),
        "card-fg-color": fg,
        "popover-bg-color": _mix(bg, fg, 0.08),
        "popover-fg-color": fg,
        "dialog-bg-color": _mix(bg, fg, 0.06),
        "dialog-fg-color": fg,
    }
    body = "\n".join(f"  --{k}: {v};" for k, v in tokens.items())
    return f":root {{\n{body}\n}}\n"


STYLE = """
.layout-stage {
  border-radius: 16px;
  background-color: color-mix(in srgb, var(--window-bg-color) 55%, black);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--window-fg-color) 8%, transparent);
}
.connect-button {
  padding: 8px 32px;
  font-weight: 700;
}
.log-view {
  border-radius: 12px;
  padding: 10px;
  background-color: color-mix(in srgb, var(--window-bg-color) 70%, black);
}
.status-ok { color: var(--success-color); }
.status-error { color: var(--error-color); }
"""


# ── Helpers ──────────────────────────────────────────────────────────────
def run_async(fn, on_done=None, on_error=None):
    """Run `fn()` off the main loop; deliver the result/exception back on it."""
    def deliver(cb, value):
        cb(value)
        return GLib.SOURCE_REMOVE

    def worker():
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 — reported to the UI
            if on_error:
                GLib.idle_add(deliver, on_error, e)
            else:
                traceback.print_exc()
            return
        if on_done:
            GLib.idle_add(deliver, on_done, result)

    threading.Thread(target=worker, daemon=True).start()


def summarize_error(log: str) -> str:
    codes = "|".join(re.escape(k) for k in FRIENDLY_ERRORS)
    for line in reversed(log.splitlines()):
        match = re.search(codes, line)
        if match:
            return FRIENDLY_ERRORS[match.group(0)]
    return ""


def _rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


# ── Monitor layout preview ───────────────────────────────────────────────
class MonitorLayout(Gtk.DrawingArea):
    """The local monitors to scale; clicking one includes/excludes it."""

    PAD = 20
    GAP = 3

    def __init__(self, on_toggle):
        super().__init__(content_height=260, hexpand=True)
        self.on_toggle = on_toggle
        self.monitors: list[Monitor] = []
        self.excluded: set[str] = set()
        self.single = False
        self.colors = load_colors()
        self.hover: str | None = None
        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.connect("released", self._clicked)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self._set_hover(self._monitor_at(x, y)))
        motion.connect("leave", lambda *_: self._set_hover(None))
        self.add_controller(motion)

    def update(self, monitors, excluded, single) -> None:
        self.monitors, self.excluded, self.single = monitors, set(excluded), single
        self.queue_draw()

    def set_colors(self, colors) -> None:
        self.colors = colors
        self.queue_draw()

    def is_used(self, m: Monitor) -> bool:
        if self.single:
            return m is primary_of(self.monitors)
        return m.name not in self.excluded

    def _rects(self) -> dict[str, tuple[float, float, float, float]]:
        if not self.monitors:
            return {}
        width, height = self.get_width(), self.get_height()
        min_x, min_y, bw, bh = layout_bbox(self.monitors)
        k = min((width - 2 * self.PAD) / bw, (height - 2 * self.PAD) / bh)
        ox = (width - bw * k) / 2 - min_x * k
        oy = (height - bh * k) / 2 - min_y * k
        return {m.name: (ox + m.x * k, oy + m.y * k, m.logical[0] * k, m.logical[1] * k)
                for m in self.monitors}

    def _monitor_at(self, px, py) -> str | None:
        for name, (x, y, w, h) in self._rects().items():
            if x <= px <= x + w and y <= py <= y + h:
                return name
        return None

    def _set_hover(self, name) -> None:
        if self.single:
            name = None
        if name != self.hover:
            self.hover = name
            self.set_cursor_from_name("pointer" if name else None)
            self.queue_draw()

    def _clicked(self, _gesture, _n, x, y) -> None:
        name = self._monitor_at(x, y)
        if name and not self.single:
            self.on_toggle(name)

    def _draw(self, _area, cr, width, height) -> None:
        fg = [c / 255 for c in _rgb(self.colors["foreground"])]
        accent_hex = self.colors["accent"]
        accent = [c / 255 for c in _rgb(accent_hex)]
        on_accent = [c / 255 for c in _rgb(on_color(self.colors, accent_hex))]
        rects = self._rects()

        if not rects:
            layout = self.create_pango_layout("No se detectaron monitores locales")
            tw, th = layout.get_pixel_size()
            cr.set_source_rgba(*fg, 0.5)
            cr.move_to((width - tw) / 2, (height - th) / 2)
            PangoCairo.show_layout(cr, layout)
            return

        primary = primary_of(self.monitors)
        for m in self.monitors:
            x, y, w, h = rects[m.name]
            x, y, w, h = x + self.GAP, y + self.GAP, w - 2 * self.GAP, h - 2 * self.GAP
            used = self.is_used(m)
            hovered = m.name == self.hover

            _rounded_rect(cr, x, y, w, h, 10)
            if used:
                cr.set_source_rgba(*accent, 1.0 if hovered else 0.85)
                cr.fill()
            else:
                cr.set_source_rgba(*fg, 0.10 if hovered else 0.05)
                cr.fill_preserve()
                cr.set_source_rgba(*fg, 0.35)
                cr.set_line_width(1.5)
                cr.set_dash([6, 4])
                cr.stroke()
                cr.set_dash([])

            lines = [f"<b>{GLib.markup_escape_text(m.name)}</b>", f"{m.width}×{m.height}"]
            if m is primary:
                lines.append("principal")
            elif not used:
                lines.append("excluido")
            layout = self.create_pango_layout(None)
            layout.set_alignment(Pango.Alignment.CENTER)
            layout.set_width(int(max(w - 12, 1) * Pango.SCALE))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            layout.set_markup("\n".join(lines), -1)
            # Narrow (portrait) or small monitors: fewer lines rather than "108…"
            while len(lines) > 1 and (layout.is_ellipsized() or layout.get_pixel_size()[1] > h - 8):
                lines.pop()
                layout.set_markup("\n".join(lines), -1)
            tw, th = layout.get_pixel_size()
            if used:
                cr.set_source_rgb(*on_accent)
            else:
                cr.set_source_rgba(*fg, 0.6)
            cr.move_to(x + (w - layout.get_width() / Pango.SCALE) / 2, y + (h - th) / 2)
            PangoCairo.show_layout(cr, layout)


# ── Main window ──────────────────────────────────────────────────────────
class LauncherWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="FreeRDP", default_width=1040,
                         default_height=780)
        self.set_size_request(380, 480)
        self.profiles = load_profiles()
        self.current: str | None = None      # saved name of the profile on screen
        self.monitors: list[Monitor] = []
        self.excluded: set[str] | None = None
        self._loading = False
        self._dirty = False
        self._rows: dict[str, Adw.ActionRow] = {}

        # Sidebar: profiles
        self.listbox = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.listbox.set_placeholder(Gtk.Label(label="Sin perfiles guardados",
                                               css_classes=["dim-label"], margin_top=24))
        self.listbox.connect("row-selected", self._on_row_selected)
        side_header = Adw.HeaderBar()
        side_header.pack_start(Gtk.Button(icon_name="list-add-symbolic",
                                          action_name="win.new-profile",
                                          tooltip_text="Nuevo perfil (Ctrl+N)"))
        sidebar = Adw.ToolbarView(content=Gtk.ScrolledWindow(
            child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True))
        sidebar.add_top_bar(side_header)

        # Content: form
        self.title = Adw.WindowTitle()
        header = Adw.HeaderBar(title_widget=self.title)
        self.save_button = Gtk.Button(icon_name="document-save-symbolic",
                                      action_name="win.save", tooltip_text="Guardar (Ctrl+S)")
        menu = Gio.Menu()
        profile_section = Gio.Menu()
        profile_section.append("Duplicar perfil", "win.duplicate")
        profile_section.append("Eliminar perfil", "win.delete")
        menu.append_section(None, profile_section)
        tools = Gio.Menu()
        tools.append("Ver log de la última conexión", "win.show-log")
        tools.append("Crear acceso en el menú de apps", "win.install-shortcut")
        menu.append_section(None, tools)
        app_section = Gio.Menu()
        app_section.append("Atajos de teclado", "app.shortcuts")
        app_section.append("Acerca de FreeRDP Launcher", "app.about")
        menu.append_section(None, app_section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       primary=True, tooltip_text="Menú principal"))
        header.pack_end(self.save_button)

        page = Adw.PreferencesPage()
        page.add(self._connection_group())
        page.add(self._display_group())
        page.add(self._display_options_group())
        page.add(self._redirection_group())
        page.add(self._advanced_group())

        self.status = Gtk.Label(css_classes=["dim-label"], ellipsize=Pango.EllipsizeMode.END,
                                xalign=0, hexpand=True)
        self.spinner = Adw.Spinner(visible=False)
        self.connect_button = Gtk.Button(
            child=Adw.ButtonContent(icon_name="media-playback-start-symbolic", label="Conectar"),
            action_name="win.connect", tooltip_text="Conectar (Ctrl+Enter)",
            css_classes=["suggested-action", "pill", "connect-button"])
        bottom = Gtk.ActionBar()
        status_box = Gtk.Box(spacing=8, margin_start=6)
        status_box.append(self.spinner)
        status_box.append(self.status)
        bottom.pack_start(status_box)
        bottom.pack_end(self.connect_button)

        content = Adw.ToolbarView(content=page)
        content.add_top_bar(header)
        content.add_bottom_bar(bottom)

        self.split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(child=sidebar, title="Perfiles"),
            content=Adw.NavigationPage(child=content, title="Conexión"),
            min_sidebar_width=220, max_sidebar_width=300)
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        self._install_actions()
        self._render_list()
        if self.profiles:
            self._select(next(iter(self.profiles)))
        else:
            self.new_profile()
        self.refresh_monitors()

    # ── Form ─────────────────────────────────────────────────────────────
    def _entry(self, group, key, title, cls=Adw.EntryRow, **props):
        row = cls(title=title, **props)
        row.connect("changed", self._changed)
        group.add(row)
        self.entries[key] = row
        return row

    def _switch(self, group, key, title, subtitle=""):
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.connect("notify::active", self._changed)
        group.add(row)
        self.switches[key] = row
        return row

    def _connection_group(self):
        self.entries: dict[str, Adw.EntryRow] = {}
        self.switches: dict[str, Adw.SwitchRow] = {}
        group = Adw.PreferencesGroup(title="Conexión")
        self._entry(group, "name", "Nombre del perfil")
        self._entry(group, "host", "Host o IP")
        self._entry(group, "port", "Puerto", input_purpose=Gtk.InputPurpose.DIGITS)
        self._entry(group, "user", "Usuario")
        self._entry(group, "pass", "Contraseña", cls=Adw.PasswordEntryRow)
        self._entry(group, "domain", "Dominio (opcional)")
        self.entries["host"].connect("changed", lambda *_: self._update_title())
        self.entries["name"].connect("changed", lambda *_: self._update_title())
        return group

    def _display_group(self):
        group = Adw.PreferencesGroup(
            title="Monitores",
            description="Haz clic en un monitor para incluirlo o sacarlo de la sesión.")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", action_name="win.refresh-monitors",
                             tooltip_text="Volver a detectar monitores (F5)",
                             css_classes=["flat"], valign=Gtk.Align.CENTER)
        group.set_header_suffix(refresh)
        self.layout = MonitorLayout(self._toggle_monitor)
        stage = Gtk.Frame(child=self.layout, css_classes=["layout-stage"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(stage)
        self.layout_info = Gtk.Label(wrap=True, xalign=0, css_classes=["dim-label"],
                                     margin_start=4)
        box.append(self.layout_info)
        group.add(box)
        return group

    def _display_options_group(self):
        group = Adw.PreferencesGroup()
        self._switch(group, "multimon", "Usar varios monitores",
                     "Extiende el escritorio de Windows a los monitores marcados")
        self._switch(group, "fullscreen", "Pantalla completa")
        self._switch(group, "dyn_res", "Resolución dinámica",
                     "Ajusta la sesión cuando cambia el tamaño de la ventana")
        self.switches["multimon"].connect("notify::active", lambda *_: self._update_layout())
        return group

    def _redirection_group(self):
        group = Adw.PreferencesGroup(title="Redirección")
        self._switch(group, "audio", "Sonido")
        self._switch(group, "microphone", "Micrófono")
        self._switch(group, "camera", "Cámara")
        self._switch(group, "clipboard", "Portapapeles")
        return group

    def _advanced_group(self):
        group = Adw.PreferencesGroup(title="Avanzado")
        self.security = Adw.ComboRow(
            title="Seguridad",
            subtitle="Si el servidor rechaza la negociación automática, fuerza un nivel",
            model=Gtk.StringList.new([label for _, label in SECURITY]))
        self.security.connect("notify::selected", self._changed)
        group.add(self.security)
        self._switch(group, "gfx", "Gráficos GFX (H.264 AVC444)")
        self._switch(group, "ignore_cert", "Ignorar certificados")
        return group

    def _load_form(self, name: str, data: dict) -> None:
        self._loading = True
        data = {**DEFAULTS, **data}
        self.entries["name"].set_text(name)
        for key in ("host", "port", "user", "pass", "domain"):
            self.entries[key].set_text(str(data[key] or ""))
        for key, row in self.switches.items():
            row.set_active(bool(data[key]))
        keys = [k for k, _ in SECURITY]
        self.security.set_selected(keys.index(data["security"]) if data["security"] in keys else 0)
        excluded = data["excluded_monitors"]
        self.excluded = set(excluded) if excluded is not None else None
        self._loading = False
        self._set_dirty(False)
        self._update_layout()

    def _form_data(self) -> dict:
        data = {key: self.entries[key].get_text().strip() for key in ("host", "port", "user", "domain")}
        data["pass"] = self.entries["pass"].get_text()
        data["port"] = data["port"] or "3389"
        for key, row in self.switches.items():
            data[key] = row.get_active()
        data["security"] = SECURITY[self.security.get_selected()][0]
        data["excluded_monitors"] = sorted(self.excluded) if self.excluded is not None else None
        return data

    def _changed(self, *_):
        if not self._loading:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self.save_button.add_css_class("suggested-action")
        else:
            self.save_button.remove_css_class("suggested-action")
        self._update_title()

    def _update_title(self) -> None:
        name = self.entries["name"].get_text().strip() or "Nuevo perfil"
        host = self.entries["host"].get_text().strip()
        port = self.entries["port"].get_text().strip()
        subtitle = f"{host}:{port}" if host and port not in ("", "3389") else host
        if self._dirty:
            subtitle = f"{subtitle} · sin guardar" if subtitle else "sin guardar"
        self.title.set_title(name)
        self.title.set_subtitle(subtitle)

    # ── Monitors ─────────────────────────────────────────────────────────
    def refresh_monitors(self) -> None:
        def done(monitors):
            self.monitors = monitors
            self._update_layout()
        run_async(detect_monitors, done, lambda e: self.toast(f"No se detectaron monitores: {e}"))

    def _effective_excluded(self) -> set[str]:
        if self.excluded is not None:
            return self.excluded
        return {m.name for m in self.monitors if m.is_tv}

    def _toggle_monitor(self, name: str) -> None:
        excluded = set(self._effective_excluded())
        if name in excluded:
            excluded.discard(name)
        else:
            remaining = [m for m in self.monitors if m.name not in excluded and m.name != name]
            if not remaining:
                self.toast("Debe quedar al menos un monitor en la sesión")
                return
            excluded.add(name)
        self.excluded = excluded
        self._changed()
        self._update_layout()

    def _update_layout(self) -> None:
        single = not self.switches["multimon"].get_active()
        excluded = self._effective_excluded()
        self.layout.update(self.monitors, excluded, single)
        self.layout_info.set_label(self._layout_summary(single, excluded))

    def _layout_summary(self, single: bool, excluded: set[str]) -> str:
        if not self.monitors:
            return "No se pudo leer la disposición de monitores de Hyprland."
        if single:
            p = primary_of(self.monitors)
            return f"Un solo monitor: {p.name} ({p.width}×{p.height})."
        used = [m for m in self.monitors if m.name not in excluded]
        if not used:
            return "Ningún monitor seleccionado."
        _, _, w, h = layout_bbox(used)
        text = (f"{len(used)} {'monitor' if len(used) == 1 else 'monitores'} · "
                f"escritorio remoto de {round(w)}×{round(h)}")
        left_out = [m.name for m in self.monitors if m.name in excluded]
        if left_out:
            text += f" · sin {', '.join(left_out)}"
        loose = [m.name for m in used
                 if len(used) > 1 and not any(touches(m, o) for o in used if o is not m)]
        if loose:
            text += f"\n⚠ {', '.join(loose)} no toca a los demás monitores elegidos."
        return text

    # ── Profiles list ────────────────────────────────────────────────────
    def _render_list(self) -> None:
        self._loading = True
        self.listbox.remove_all()
        self._rows.clear()
        for name, data in self.profiles.items():
            host = data.get("host", "")
            user = data.get("user", "")
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), title_lines=1,
                                subtitle=GLib.markup_escape_text(host), subtitle_lines=1,
                                tooltip_text=f"{user} en {host}" if user else host)
            row.add_prefix(Gtk.Image(icon_name="computer-symbolic"))
            self.listbox.append(row)
            self._rows[name] = row
        if self.current in self._rows:
            self.listbox.select_row(self._rows[self.current])
        self._loading = False

    def _row_name(self, row) -> str | None:
        return next((n for n, r in self._rows.items() if r is row), None)

    def _on_row_selected(self, _listbox, row) -> None:
        if self._loading or row is None:
            return
        name = self._row_name(row)
        if name is None or name == self.current:
            self.split.set_show_content(True)
            return
        if self._dirty:
            self._confirm_discard(lambda: self._select(name), self._reselect_current)
        else:
            self._select(name)

    def _reselect_current(self) -> None:
        self._loading = True
        if self.current in self._rows:
            self.listbox.select_row(self._rows[self.current])
        else:
            self.listbox.unselect_all()
        self._loading = False

    def _select(self, name: str) -> None:
        self.current = name
        self._reselect_current()
        self._load_form(name, self.profiles[name])
        self.lookup_action("delete").set_enabled(True)
        self.lookup_action("duplicate").set_enabled(True)
        self.split.set_show_content(True)

    def _confirm_discard(self, proceed, cancel) -> None:
        dialog = Adw.AlertDialog(heading="¿Guardar los cambios?",
                                 body="El perfil tiene cambios sin guardar.")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("discard", "Descartar")
        dialog.add_response("save", "Guardar")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response == "save" and self.save_profile():
                proceed()
            elif response == "discard":
                proceed()
            else:
                cancel()
        dialog.connect("response", on_response)
        dialog.present(self)

    # ── Actions ──────────────────────────────────────────────────────────
    def _install_actions(self) -> None:
        for name, callback in (("new-profile", self._new_profile_action),
                               ("save", self.save_profile),
                               ("duplicate", self.duplicate_profile),
                               ("delete", self.confirm_delete),
                               ("connect", self.connect_rdp),
                               ("refresh-monitors", self.refresh_monitors),
                               ("show-log", self.show_log),
                               ("install-shortcut", self.install_shortcut)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, cb=callback: cb())
            self.add_action(action)

    def toast(self, title: str, timeout: int = 3) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(title), timeout=timeout))

    def _new_profile_action(self) -> None:
        if self._dirty:
            self._confirm_discard(self.new_profile, lambda: None)
        else:
            self.new_profile()

    def new_profile(self) -> None:
        self.current = None
        self._reselect_current()
        self._load_form("Nuevo perfil", DEFAULTS)
        self.lookup_action("delete").set_enabled(False)
        self.lookup_action("duplicate").set_enabled(False)
        self.split.set_show_content(True)
        self.entries["host"].grab_focus()

    def save_profile(self) -> bool:
        name = self.entries["name"].get_text().strip()
        data = self._form_data()
        if not name:
            self.toast("Ponle un nombre al perfil")
            self.entries["name"].grab_focus()
            return False
        if not data["host"]:
            self.toast("Falta el host o la IP")
            self.entries["host"].grab_focus()
            return False
        if not data["port"].isdigit() or not 0 < int(data["port"]) < 65536:
            self.toast("El puerto debe ser un número entre 1 y 65535")
            self.entries["port"].grab_focus()
            return False
        if name != self.current and name in self.profiles:
            self.toast(f"Ya existe un perfil llamado «{name}»")
            self.entries["name"].grab_focus()
            return False

        if self.current and self.current != name:     # rename in place, keep the order
            self.profiles = {(name if k == self.current else k): v
                             for k, v in self.profiles.items()}
        self.profiles[name] = data
        try:
            save_profiles(self.profiles)
        except OSError as e:
            self.toast(f"No se pudo guardar: {e}", timeout=6)
            return False
        self.current = name
        self._render_list()
        self.lookup_action("delete").set_enabled(True)
        self.lookup_action("duplicate").set_enabled(True)
        self._set_dirty(False)
        self.toast(f"Perfil «{name}» guardado")
        return True

    def duplicate_profile(self) -> None:
        if not self.current:
            return
        base = f"{self.current} (copia)"
        name, n = base, 2
        while name in self.profiles:
            name, n = f"{base} {n}", n + 1
        data = self._form_data()
        self.current = None
        self._reselect_current()
        self._load_form(name, data)
        self._set_dirty(True)
        self.lookup_action("delete").set_enabled(False)
        self.lookup_action("duplicate").set_enabled(False)
        self.toast("Copia creada: guárdala para conservarla")

    def confirm_delete(self) -> None:
        if not self.current:
            return
        name = self.current
        dialog = Adw.AlertDialog(heading="¿Eliminar el perfil?",
                                 body=f"Se borrará «{name}» con su contraseña guardada.")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("delete", "Eliminar")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response != "delete":
                return
            del self.profiles[name]
            try:
                save_profiles(self.profiles)
            except OSError as e:
                self.toast(f"No se pudo guardar: {e}", timeout=6)
            self.current = None
            self._render_list()
            if self.profiles:
                self._select(next(iter(self.profiles)))
            else:
                self.new_profile()
            self.toast(f"Perfil «{name}» eliminado")
        dialog.connect("response", on_response)
        dialog.present(self)

    # ── Connect ──────────────────────────────────────────────────────────
    def _set_status(self, text: str, css: str | None = None, busy: bool = False) -> None:
        self.status.set_label(text)
        for cls in ("status-ok", "status-error"):
            self.status.remove_css_class(cls)
        if css:
            self.status.add_css_class(css)
        self.spinner.set_visible(busy)

    def connect_rdp(self) -> None:
        data = self._form_data()
        if not data["host"]:
            self.toast("Falta el host o la IP")
            self.entries["host"].grab_focus()
            return
        binary = find_binary()
        if not binary:
            self.toast("No se encontró sdl-freerdp (compilado o del sistema)", timeout=6)
            return

        self.lookup_action("connect").set_enabled(False)
        self._set_status("Preparando conexión…", busy=True)
        excluded = self._effective_excluded()
        used = [m.name for m in self.monitors if m.name not in excluded]
        need_ids = data["multimon"] and bool(excluded & {m.name for m in self.monitors})

        def done(ids):
            missing = [n for n in used if n not in ids]
            if need_ids and missing:
                self.toast(f"FreeRDP no ve {', '.join(missing)}; se conecta sin ese monitor",
                           timeout=6)
            monitor_ids = [ids[n] for n in used if n in ids] if need_ids else []
            self._launch(binary, data, monitor_ids)

        run_async(lambda: sdl_monitor_ids(binary) if need_ids else {}, done,
                  lambda e: self._launch_failed(e))

    def _build_command(self, binary: str, data: dict, monitor_ids: list[int]) -> list[str]:
        host, port = data["host"], data["port"]
        cmd = [binary, f"/v:{host}:{port}" if port and port != "3389" else f"/v:{host}"]
        if data["user"]:
            cmd.append(f"/u:{data['user']}")
        if data["pass"]:
            cmd.append(f"/p:{data['pass']}")
        if data["domain"]:
            cmd.append(f"/d:{data['domain']}")
        if data["security"] != "auto":
            cmd.append(f"/sec:{data['security']}")
        if data["multimon"]:
            cmd.append("/multimon")
            if monitor_ids:
                cmd.append("/monitors:" + ",".join(str(i) for i in monitor_ids))
        if data["fullscreen"]:
            cmd.append("/f")
        if data["audio"]:
            cmd.append("/sound")
        if data["clipboard"]:
            cmd.append("/clipboard")
        if data["ignore_cert"]:
            cmd.append("/cert:ignore")
        if data["dyn_res"]:
            cmd.append("/dynamic-resolution")
        cmd.append("/auto-reconnect")
        if data["microphone"]:
            cmd.append("/microphone:sys:alsa")
        if data["camera"]:
            cmd.append("/dvc:rdpecam")
        if data["gfx"]:
            cmd.append("/gfx:AVC444")
        if data["audio"] or data["microphone"] or data["camera"]:
            cmd.append("/log-filters:com.freerdp.channels.rdpsnd:DEBUG,"
                       "com.freerdp.channels.audin:DEBUG,"
                       "com.freerdp.channels.rdpecam:DEBUG,"
                       "com.freerdp.channels.drdynvc:DEBUG")
        return cmd

    def _launch(self, binary: str, data: dict, monitor_ids: list[int]) -> None:
        cmd = self._build_command(binary, data, monitor_ids)
        env = os.environ.copy()
        local_lib = str(Path.home() / ".local/lib")
        env["LD_LIBRARY_PATH"] = (f"{local_lib}:{env['LD_LIBRARY_PATH']}"
                                  if env.get("LD_LIBRARY_PATH") else local_lib)
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            log = open(LOG_FILE, "w")
            proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=log)
        except OSError as e:
            self._launch_failed(e)
            return
        self._set_status(f"Conectando a {data['host']}…", busy=True)
        self._watch(proc, log, 0)

    def _launch_failed(self, error) -> None:
        self.lookup_action("connect").set_enabled(True)
        self._set_status("Error al ejecutar FreeRDP", "status-error")
        self.toast(f"No se pudo ejecutar FreeRDP: {error}", timeout=6)

    def _watch(self, proc, log, elapsed_ms: int) -> None:
        """Keep polling while the client lives so a late failure is still reported."""
        ret = proc.poll()
        if ret is not None:
            log.close()
            self.lookup_action("connect").set_enabled(True)
            if ret != 0:
                self._set_status("La conexión falló", "status-error")
                self.show_log(failed_code=ret)
            else:
                self._set_status("Sesión finalizada")
            return
        if elapsed_ms == STARTUP_GRACE_MS:
            self._set_status("Sesión iniciada", "status-ok")
            self.lookup_action("connect").set_enabled(True)
        step = 200 if elapsed_ms < STARTUP_GRACE_MS else 1000
        GLib.timeout_add(step, lambda: (self._watch(proc, log, elapsed_ms + step),
                                        GLib.SOURCE_REMOVE)[1])

    # ── Log / shortcut ───────────────────────────────────────────────────
    def show_log(self, failed_code: int | None = None) -> None:
        try:
            text = LOG_FILE.read_text(errors="replace").strip()
        except OSError:
            text = ""
        if failed_code is None:
            heading, body = "Última conexión", str(LOG_FILE)
        else:
            heading = "La conexión falló"
            body = summarize_error(text) or f"sdl-freerdp terminó con código {failed_code}."

        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            css_classes=["log-view"], cursor_visible=False)
        view.get_buffer().set_text(text or "(sin registro)")
        scroller = Gtk.ScrolledWindow(child=view, min_content_height=320,
                                      min_content_width=640, vexpand=True)
        GLib.idle_add(lambda: (scroller.get_vadjustment().set_value(
            scroller.get_vadjustment().get_upper()), GLib.SOURCE_REMOVE)[1])

        dialog = Adw.AlertDialog(heading=heading, body=body, extra_child=scroller,
                                 prefer_wide_layout=True)
        dialog.add_response("copy", "Copiar")
        dialog.add_response("close", "Cerrar")
        dialog.set_default_response("close")
        dialog.set_close_response("close")

        def on_response(_d, response):
            if response == "copy":
                self.get_clipboard().set(text)
                self.toast("Log copiado al portapapeles")
        dialog.connect("response", on_response)
        dialog.present(self)

    def install_shortcut(self) -> None:
        script = Path(__file__).resolve()
        try:
            BIN_LINK.parent.mkdir(parents=True, exist_ok=True)
            if BIN_LINK.is_symlink() or BIN_LINK.exists():
                if BIN_LINK.resolve() != script:
                    BIN_LINK.unlink()
            if not BIN_LINK.exists():
                BIN_LINK.symlink_to(script)
            DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            DESKTOP_FILE.write_text(
                "[Desktop Entry]\n"
                "Name=FreeRDP\n"
                "Comment=FreeRDP SDL3 Remote Desktop Client (Custom Multimonitor Build)\n"
                f"Exec={BIN_LINK}\n"
                "Icon=preferences-desktop-remote\n"
                "Terminal=false\n"
                "Type=Application\n"
                "Categories=Network;RemoteAccess;\n"
                "StartupNotify=true\n"
                f"StartupWMClass={APP_ID}\n")
        except OSError as e:
            self.toast(f"No se pudo crear el acceso: {e}", timeout=6)
            return
        self.toast("Acceso creado en el menú de aplicaciones")


# ── Application ──────────────────────────────────────────────────────────
ACCELS = {
    "win.connect": ["<Ctrl>Return"],
    "win.save": ["<Ctrl>s"],
    "win.new-profile": ["<Ctrl>n"],
    "win.duplicate": ["<Ctrl><Shift>d"],
    "win.refresh-monitors": ["F5"],
    "win.show-log": ["<Ctrl>l"],
    "app.shortcuts": ["<Ctrl>question"],
    "app.quit": ["<Ctrl>q"],
}

SHORTCUTS = [
    ("Conexión", [("Conectar", "<Ctrl>Return"), ("Ver log de la última conexión", "<Ctrl>l"),
                  ("Volver a detectar monitores", "F5")]),
    ("Perfiles", [("Nuevo perfil", "<Ctrl>n"), ("Guardar", "<Ctrl>s"),
                  ("Duplicar", "<Ctrl><Shift>d")]),
    ("General", [("Atajos de teclado", "<Ctrl>question"), ("Salir", "<Ctrl>q")]),
]


class LauncherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._theme_provider = Gtk.CssProvider()
        self._theme_sig = None
        self.window: LauncherWindow | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        style = Gtk.CssProvider()
        style.load_from_string(STYLE)
        Gtk.StyleContext.add_provider_for_display(
            display, style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.StyleContext.add_provider_for_display(
            display, self._theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._reload_theme()
        GLib.timeout_add_seconds(THEME_POLL_SECONDS, self._poll_theme)

        for name, callback in (("shortcuts", self._shortcuts), ("about", self._about),
                               ("quit", self.quit)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, cb=callback: cb())
            self.add_action(action)
        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

    def do_activate(self):
        if self.window is None:
            self.window = LauncherWindow(self)
            self.window.layout.set_colors(load_colors())
        self.window.present()

    def _reload_theme(self):
        colors = load_colors()
        self._theme_sig = theme_signature()
        self._theme_provider.load_from_string(theme_css(colors))
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if is_dark(colors) else Adw.ColorScheme.FORCE_LIGHT)
        if self.window:
            self.window.layout.set_colors(colors)

    def _poll_theme(self):
        # Omarchy rewrites current/theme in place on `omarchy theme set`
        if theme_signature() != self._theme_sig:
            self._reload_theme()
            if self.window:
                self.window.toast("Tema de Omarchy actualizado")
        return GLib.SOURCE_CONTINUE

    def _shortcuts(self):
        dialog = Adw.ShortcutsDialog()
        for title, items in SHORTCUTS:
            section = Adw.ShortcutsSection.new(title)
            for label, accel in items:
                section.add(Adw.ShortcutsItem.new(label, accel))
            dialog.add(section)
        dialog.present(self.window)

    def _about(self):
        Adw.AboutDialog(
            application_name="FreeRDP Launcher",
            application_icon="preferences-desktop-remote",
            version=VERSION,
            comments="Perfiles y selección de monitores para el cliente sdl-freerdp "
                     "compilado con los arreglos multimonitor para Wayland.",
            license_type=Gtk.License.APACHE_2_0,
        ).present(self.window)


def main() -> int:
    return LauncherApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
