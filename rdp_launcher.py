#!/usr/bin/env python3
import os
import sys
import json
import base64
import subprocess
import tkinter as tk
from tkinter import messagebox

# Theme Colors
BG_COLOR = "#0F172A"       # Slate 900
SIDEBAR_BG = "#1E293B"    # Slate 800
CARD_BG = "#334155"       # Slate 700
ACCENT_COLOR = "#3B82F6"  # Blue 500
ACCENT_HOVER = "#2563EB"  # Blue 600
TEXT_COLOR = "#F8FAFC"    # Slate 50
TEXT_MUTED = "#94A3B8"    # Slate 400
ERROR_COLOR = "#EF4444"   # Red 500
ERROR_HOVER = "#DC2626"   # Red 600
SUCCESS_COLOR = "#10B981" # Emerald 500
SUCCESS_HOVER = "#059669" # Emerald 600

CONFIG_DIR = os.path.expanduser("~/.config/freerdp")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
DEFAULT_BINARY = "/home/edopex/.gemini/antigravity/scratch/FreeRDP/build/client/SDL/SDL3/sdl-freerdp"
FALLBACK_BINARY = "/usr/bin/sdl-freerdp3"

def obfuscate_password(password):
    if not password:
        return ""
    try:
        encoded = base64.b64encode(password.encode("utf-8")).decode("utf-8")
        return f"b64:{encoded}"
    except Exception:
        return password

def deobfuscate_password(obfuscated):
    if not obfuscated:
        return ""
    if obfuscated.startswith("b64:"):
        try:
            decoded_bytes = base64.b64decode(obfuscated[4:].encode("utf-8"), validate=True)
            return decoded_bytes.decode("utf-8")
        except Exception:
            return obfuscated
    return obfuscated

def load_profiles():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r") as f:
                profiles = json.load(f)
                for name, data in profiles.items():
                    if "pass" in data:
                        data["pass"] = deobfuscate_password(data["pass"])
                return profiles
        except Exception:
            pass
    return {}

def save_profiles(profiles):
    profiles_to_save = {}
    for name, data in profiles.items():
        profiles_to_save[name] = data.copy()
        if "pass" in profiles_to_save[name]:
            profiles_to_save[name]["pass"] = obfuscate_password(profiles_to_save[name]["pass"])
    try:
        with open(PROFILES_FILE, "w") as f:
            json.dump(profiles_to_save, f, indent=4)
    except Exception as e:
        messagebox.showerror("Error", f"No se pudieron guardar los perfiles: {e}")

class RDPLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FreeRDP Connection Manager")
        self.root.geometry("850x550")
        self.root.configure(bg=BG_COLOR)
        
        self.profiles = load_profiles()
        self.current_profile_name = None
        self.show_password = False

        # Left Sidebar (Profiles list)
        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=250)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        # Main Panel (Form)
        self.main_panel = tk.Frame(self.root, bg=BG_COLOR, padx=30, pady=25)
        self.main_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.setup_sidebar()
        self.setup_main_panel()
        
        # Load first profile if exists
        if self.profiles:
            first_name = list(self.profiles.keys())[0]
            self.select_profile(first_name)
        else:
            self.new_profile()

    def setup_sidebar(self):
        # Sidebar Header
        lbl = tk.Label(self.sidebar, text="Perfiles RDP", font=("Arial", 16, "bold"), fg=TEXT_COLOR, bg=SIDEBAR_BG, pady=15)
        lbl.pack(fill=tk.X)

        # Profiles List Frame
        self.list_frame = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        self.list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.profile_buttons = {}
        self.render_profiles_list()

        # Sidebar Bottom Action Button
        btn_new = tk.Button(self.sidebar, text="+ Nuevo Perfil", font=("Arial", 11, "bold"), 
                            fg=TEXT_COLOR, bg=SUCCESS_COLOR, activeforeground=TEXT_COLOR, activebackground=SUCCESS_HOVER,
                            bd=0, cursor="hand2", pady=10, command=self.new_profile)
        btn_new.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=15)
        btn_new.bind("<Enter>", lambda e: btn_new.configure(bg=SUCCESS_HOVER))
        btn_new.bind("<Leave>", lambda e: btn_new.configure(bg=SUCCESS_COLOR))

    def render_profiles_list(self):
        for widget in self.list_frame.winfo_children():
            widget.destroy()

        self.profile_buttons.clear()
        
        if not self.profiles:
            lbl = tk.Label(self.list_frame, text="No hay perfiles guardados", font=("Arial", 10, "italic"), fg=TEXT_MUTED, bg=SIDEBAR_BG, pady=20)
            lbl.pack()
            return

        for name in self.profiles.keys():
            btn = tk.Button(self.list_frame, text=name, font=("Arial", 11), anchor="w",
                            fg=TEXT_COLOR, bg=SIDEBAR_BG, activeforeground=TEXT_COLOR, activebackground=CARD_BG,
                            bd=0, cursor="hand2", padx=15, pady=8, command=lambda n=name: self.select_profile(n))
            btn.pack(fill=tk.X, pady=2)
            self.profile_buttons[name] = btn
            
            # Hover effect
            btn.bind("<Enter>", lambda e, b=btn: self.on_btn_enter(b))
            btn.bind("<Leave>", lambda e, b=btn, n=name: self.on_btn_leave(b, n))

    def on_btn_enter(self, btn):
        if btn["background"] != CARD_BG:
            btn.configure(bg=CARD_BG)

    def on_btn_leave(self, btn, name):
        if name != self.current_profile_name:
            btn.configure(bg=SIDEBAR_BG)

    def select_profile(self, name):
        self.current_profile_name = name
        for n, btn in self.profile_buttons.items():
            if n == name:
                btn.configure(bg=CARD_BG, font=("Arial", 11, "bold"))
            else:
                btn.configure(bg=SIDEBAR_BG, font=("Arial", 11))

        data = self.profiles[name]
        self.val_name.set(name)
        self.val_host.set(data.get("host", ""))
        self.val_port.set(data.get("port", "3389"))
        self.val_user.set(data.get("user", ""))
        self.val_pass.set(data.get("pass", ""))
        self.val_domain.set(data.get("domain", ""))
        self.val_multimon.set(data.get("multimon", True))
        self.val_fullscreen.set(data.get("fullscreen", True))
        self.val_audio.set(data.get("audio", True))
        self.val_clipboard.set(data.get("clipboard", True))
        self.val_ignore_cert.set(data.get("ignore_cert", True))
        self.val_dyn_res.set(data.get("dyn_res", True))
        self.val_microphone.set(data.get("microphone", False))
        self.val_camera.set(data.get("camera", False))
        
        self.btn_delete.configure(state=tk.NORMAL, bg=ERROR_COLOR)

    def new_profile(self):
        self.current_profile_name = None
        for btn in self.profile_buttons.values():
            btn.configure(bg=SIDEBAR_BG, font=("Arial", 11))
            
        self.val_name.set("Nuevo Perfil")
        self.val_host.set("")
        self.val_port.set("3389")
        self.val_user.set("")
        self.val_pass.set("")
        self.val_domain.set("")
        self.val_multimon.set(True)
        self.val_fullscreen.set(True)
        self.val_audio.set(True)
        self.val_clipboard.set(True)
        self.val_ignore_cert.set(True)
        self.val_dyn_res.set(True)
        self.val_microphone.set(False)
        self.val_camera.set(False)
        
        self.btn_delete.configure(state=tk.DISABLED, bg="#475569")

    def setup_main_panel(self):
        # Header
        lbl_head = tk.Label(self.main_panel, text="Detalles de la Conexión", font=("Arial", 18, "bold"), fg=TEXT_COLOR, bg=BG_COLOR)
        lbl_head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))

        # Variables
        self.val_name = tk.StringVar()
        self.val_host = tk.StringVar()
        self.val_port = tk.StringVar(value="3389")
        self.val_user = tk.StringVar()
        self.val_pass = tk.StringVar()
        self.val_domain = tk.StringVar()
        self.val_multimon = tk.BooleanVar(value=True)
        self.val_fullscreen = tk.BooleanVar(value=True)
        self.val_audio = tk.BooleanVar(value=True)
        self.val_clipboard = tk.BooleanVar(value=True)
        self.val_ignore_cert = tk.BooleanVar(value=True)
        self.val_dyn_res = tk.BooleanVar(value=True)
        self.val_microphone = tk.BooleanVar(value=False)
        self.val_camera = tk.BooleanVar(value=False)

        # Form Helpers
        def add_field(row, label_text, var, show_char=None):
            lbl = tk.Label(self.main_panel, text=label_text, font=("Arial", 11), fg=TEXT_MUTED, bg=BG_COLOR)
            lbl.grid(row=row, column=0, sticky="w", pady=6)
            
            entry = tk.Entry(self.main_panel, textvariable=var, font=("Arial", 11), fg=TEXT_COLOR, bg=SIDEBAR_BG,
                             insertbackground=TEXT_COLOR, bd=0, highlightthickness=1, highlightcolor=ACCENT_COLOR,
                             highlightbackground=CARD_BG, show=show_char)
            entry.grid(row=row, column=1, columnspan=2, sticky="we", pady=6, ipady=4)
            return entry

        # Fields
        add_field(1, "Nombre Perfil:", self.val_name)
        
        # Host and Port Row
        lbl_host = tk.Label(self.main_panel, text="Host / IP:", font=("Arial", 11), fg=TEXT_MUTED, bg=BG_COLOR)
        lbl_host.grid(row=2, column=0, sticky="w", pady=6)
        
        host_port_frame = tk.Frame(self.main_panel, bg=BG_COLOR)
        host_port_frame.grid(row=2, column=1, columnspan=2, sticky="we", pady=6)
        
        entry_host = tk.Entry(host_port_frame, textvariable=self.val_host, font=("Arial", 11), fg=TEXT_COLOR, bg=SIDEBAR_BG,
                              insertbackground=TEXT_COLOR, bd=0, highlightthickness=1, highlightcolor=ACCENT_COLOR,
                              highlightbackground=CARD_BG)
        entry_host.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        
        lbl_port = tk.Label(host_port_frame, text=" Puerto:", font=("Arial", 11), fg=TEXT_MUTED, bg=BG_COLOR)
        lbl_port.pack(side=tk.LEFT, padx=(5, 2))
        
        entry_port = tk.Entry(host_port_frame, textvariable=self.val_port, font=("Arial", 11), fg=TEXT_COLOR, bg=SIDEBAR_BG,
                              insertbackground=TEXT_COLOR, bd=0, highlightthickness=1, highlightcolor=ACCENT_COLOR,
                              highlightbackground=CARD_BG, width=6)
        entry_port.pack(side=tk.LEFT, ipady=4)

        add_field(3, "Usuario:", self.val_user)
        
        # Password field with toggle button
        lbl_pass = tk.Label(self.main_panel, text="Contraseña:", font=("Arial", 11), fg=TEXT_MUTED, bg=BG_COLOR)
        lbl_pass.grid(row=4, column=0, sticky="w", pady=6)
        
        self.entry_pass = tk.Entry(self.main_panel, textvariable=self.val_pass, font=("Arial", 11), fg=TEXT_COLOR, bg=SIDEBAR_BG,
                                   insertbackground=TEXT_COLOR, bd=0, highlightthickness=1, highlightcolor=ACCENT_COLOR,
                                   highlightbackground=CARD_BG, show="*")
        self.entry_pass.grid(row=4, column=1, sticky="we", pady=6, ipady=4)
        
        self.btn_reveal = tk.Button(self.main_panel, text="Ver", font=("Arial", 9, "bold"), fg=TEXT_COLOR, bg=CARD_BG,
                                    activeforeground=TEXT_COLOR, activebackground=SIDEBAR_BG, bd=0, cursor="hand2",
                                    command=self.toggle_password_reveal, padx=8)
        self.btn_reveal.grid(row=4, column=2, sticky="e", padx=(5, 0), pady=6, ipady=2)

        add_field(5, "Dominio (Opt):", self.val_domain)

        # Options
        lbl_opts = tk.Label(self.main_panel, text="Opciones:", font=("Arial", 11), fg=TEXT_MUTED, bg=BG_COLOR)
        lbl_opts.grid(row=6, column=0, sticky="nw", pady=(15, 6))

        opts_frame = tk.Frame(self.main_panel, bg=BG_COLOR)
        opts_frame.grid(row=6, column=1, columnspan=2, sticky="w", pady=(15, 6))

        def add_check(parent, text, var):
            cb = tk.Checkbutton(parent, text=text, variable=var, font=("Arial", 10), fg=TEXT_COLOR, bg=BG_COLOR,
                                activeforeground=TEXT_COLOR, activebackground=BG_COLOR, selectcolor=BG_COLOR,
                                bd=0, highlightthickness=0)
            cb.pack(side=tk.LEFT, padx=(0, 15))

        add_check(opts_frame, "Multi-Monitor", self.val_multimon)
        add_check(opts_frame, "Pantalla Completa", self.val_fullscreen)
        
        opts_frame_2 = tk.Frame(self.main_panel, bg=BG_COLOR)
        opts_frame_2.grid(row=7, column=1, columnspan=2, sticky="w", pady=(2, 10))
        add_check(opts_frame_2, "Redirigir Audio", self.val_audio)
        add_check(opts_frame_2, "Portapapeles", self.val_clipboard)

        opts_frame_3 = tk.Frame(self.main_panel, bg=BG_COLOR)
        opts_frame_3.grid(row=8, column=1, columnspan=2, sticky="w", pady=(2, 10))
        add_check(opts_frame_3, "Ignorar Certificados", self.val_ignore_cert)
        add_check(opts_frame_3, "Resolución Dinámica", self.val_dyn_res)

        opts_frame_4 = tk.Frame(self.main_panel, bg=BG_COLOR)
        opts_frame_4.grid(row=9, column=1, columnspan=2, sticky="w", pady=(2, 10))
        add_check(opts_frame_4, "Redirigir Micrófono", self.val_microphone)
        add_check(opts_frame_4, "Redirigir Cámara", self.val_camera)

        # Actions Panel (Save, Delete, Install, Connect)
        actions_frame = tk.Frame(self.main_panel, bg=BG_COLOR)
        actions_frame.grid(row=10, column=0, columnspan=3, sticky="we", pady=(25, 0))

        # Save Button
        btn_save = tk.Button(actions_frame, text="Guardar", font=("Arial", 11, "bold"), fg=TEXT_COLOR, bg=SUCCESS_COLOR,
                             activeforeground=TEXT_COLOR, activebackground=SUCCESS_HOVER, bd=0, cursor="hand2",
                             command=self.save_current_profile, width=12, pady=8)
        btn_save.pack(side=tk.LEFT, padx=(0, 10))
        btn_save.bind("<Enter>", lambda e: btn_save.configure(bg=SUCCESS_HOVER))
        btn_save.bind("<Leave>", lambda e: btn_save.configure(bg=SUCCESS_COLOR))

        # Delete Button
        self.btn_delete = tk.Button(actions_frame, text="Eliminar", font=("Arial", 11, "bold"), fg=TEXT_COLOR, bg=ERROR_COLOR,
                                    activeforeground=TEXT_COLOR, activebackground=ERROR_HOVER, bd=0, cursor="hand2",
                                    command=self.delete_current_profile, width=12, pady=8)
        self.btn_delete.pack(side=tk.LEFT)
        self.btn_delete.bind("<Enter>", lambda e: self.btn_delete.configure(bg=ERROR_HOVER) if self.current_profile_name else None)
        self.btn_delete.bind("<Leave>", lambda e: self.btn_delete.configure(bg=ERROR_COLOR) if self.current_profile_name else None)

        # Install Shortcut Button
        btn_install = tk.Button(actions_frame, text="Crear Acceso", font=("Arial", 11, "bold"), fg=TEXT_COLOR, bg="#475569",
                                activeforeground=TEXT_COLOR, activebackground="#334155", bd=0, cursor="hand2",
                                command=self.install_desktop_shortcut, width=12, pady=8)
        btn_install.pack(side=tk.LEFT, padx=10)
        btn_install.bind("<Enter>", lambda e: btn_install.configure(bg="#334155"))
        btn_install.bind("<Leave>", lambda e: btn_install.configure(bg="#475569"))

        # BIG Connect Button
        self.btn_connect = tk.Button(actions_frame, text="CONECTAR", font=("Arial", 12, "bold"), fg=TEXT_COLOR, bg=ACCENT_COLOR,
                                activeforeground=TEXT_COLOR, activebackground=ACCENT_HOVER, bd=0, cursor="hand2",
                                command=self.connect_rdp, padx=25, pady=8)
        self.btn_connect.pack(side=tk.RIGHT)
        self.btn_connect.bind("<Enter>", lambda e: self.btn_connect.configure(bg=ACCENT_HOVER) if self.btn_connect["state"] == tk.NORMAL else None)
        self.btn_connect.bind("<Leave>", lambda e: self.btn_connect.configure(bg=ACCENT_COLOR) if self.btn_connect["state"] == tk.NORMAL else None)

        self.lbl_status = tk.Label(actions_frame, text="", font=("Arial", 11, "bold"), fg=TEXT_MUTED, bg=BG_COLOR)
        self.lbl_status.pack(side=tk.RIGHT, padx=15)

        # Grid configuration
        self.main_panel.columnconfigure(0, minsize=110)
        self.main_panel.columnconfigure(1, weight=1)
        self.main_panel.columnconfigure(2, minsize=60)

    def toggle_password_reveal(self):
        self.show_password = not self.show_password
        if self.show_password:
            self.entry_pass.configure(show="")
            self.btn_reveal.configure(text="Ocultar")
        else:
            self.entry_pass.configure(show="*")
            self.btn_reveal.configure(text="Ver")

    def save_current_profile(self):
        name = self.val_name.get().strip()
        host = self.val_host.get().strip()
        port = self.val_port.get().strip()
        user = self.val_user.get().strip()
        password = self.val_pass.get()
        domain = self.val_domain.get().strip()
        
        if not name:
            messagebox.showwarning("Advertencia", "Por favor ingresa un nombre para el perfil.")
            return
        if not host:
            messagebox.showwarning("Advertencia", "Por favor ingresa la dirección IP o Host.")
            return

        # Build data dictionary
        self.profiles[name] = {
            "host": host,
            "port": port,
            "user": user,
            "pass": password,
            "domain": domain,
            "multimon": self.val_multimon.get(),
            "fullscreen": self.val_fullscreen.get(),
            "audio": self.val_audio.get(),
            "clipboard": self.val_clipboard.get(),
            "ignore_cert": self.val_ignore_cert.get(),
            "dyn_res": self.val_dyn_res.get(),
            "microphone": self.val_microphone.get(),
            "camera": self.val_camera.get()
        }
        
        save_profiles(self.profiles)
        self.render_profiles_list()
        self.select_profile(name)
        messagebox.showinfo("Éxito", f"Perfil '{name}' guardado correctamente.")

    def delete_current_profile(self):
        if not self.current_profile_name:
            return
        
        name = self.current_profile_name
        if messagebox.askyesno("Confirmar", f"¿Estás seguro de que deseas eliminar el perfil '{name}'?"):
            del self.profiles[name]
            save_profiles(self.profiles)
            self.render_profiles_list()
            if self.profiles:
                self.select_profile(list(self.profiles.keys())[0])
            else:
                self.new_profile()

    def connect_rdp(self):
        host = self.val_host.get().strip()
        port = self.val_port.get().strip()
        user = self.val_user.get().strip()
        password = self.val_pass.get()
        domain = self.val_domain.get().strip()

        if not host:
            messagebox.showwarning("Advertencia", "Por favor ingresa el Host/IP antes de conectar.")
            return

        # Find RDP binary
        binary = DEFAULT_BINARY
        if not os.path.exists(binary):
            binary = FALLBACK_BINARY
            if not os.path.exists(binary):
                # Try path lookup
                which_check = subprocess.run(["which", "sdl-freerdp3"], capture_output=True, text=True)
                if which_check.returncode == 0:
                    binary = which_check.stdout.strip()
                else:
                    messagebox.showerror("Error", "No se encontró el ejecutable sdl-freerdp (compilado o de sistema).")
                    return

        # Build command array
        v_arg = f"/v:{host}"
        if port and port != "3389":
            v_arg = f"/v:{host}:{port}"
            
        cmd = [binary, v_arg]
        if user:
            cmd.append(f"/u:{user}")
        if password:
            cmd.append(f"/p:{password}")
        if domain:
            cmd.append(f"/d:{domain}")
        if self.val_multimon.get():
            cmd.append("/multimon")
        if self.val_fullscreen.get():
            cmd.append("/f")
        if self.val_audio.get():
            cmd.append("/sound")
        if self.val_clipboard.get():
            cmd.append("/clipboard")
        if self.val_ignore_cert.get():
            cmd.append("/cert:ignore")
        if self.val_dyn_res.get():
            cmd.append("/dynamic-resolution")
        if self.val_microphone.get():
            cmd.append("/microphone:sys:alsa")
        if self.val_camera.get():
            cmd.append("/dvc:rdpecam")
        if self.val_audio.get() or self.val_microphone.get() or self.val_camera.get():
            cmd.append("/log-filters:com.freerdp.channels.rdpsnd:DEBUG,"
                       "com.freerdp.channels.audin:DEBUG,"
                       "com.freerdp.channels.rdpecam:DEBUG,"
                       "com.freerdp.channels.drdynvc:DEBUG")

        # Launch asynchronously so GUI doesn't hang
        try:
            self.lbl_status.configure(text="Conectando...", fg=ACCENT_COLOR)
            self.btn_connect.configure(state=tk.DISABLED, bg="#475569")
            
            log_dir = os.path.expanduser("~/.config/freerdp")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            log_path = os.path.join(log_dir, "last_connection.log")
            log_file = open(log_path, "w")
            
            env = os.environ.copy()
            local_lib = os.path.expanduser("~/.local/lib")
            if "LD_LIBRARY_PATH" in env:
                env["LD_LIBRARY_PATH"] = f"{local_lib}:{env['LD_LIBRARY_PATH']}"
            else:
                env["LD_LIBRARY_PATH"] = local_lib
                
            proc = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=log_file)
            
            # Monitor process for a few seconds to detect failure
            self.root.after(100, lambda: self.monitor_process(proc, log_path, log_file, 0))
        except Exception as e:
            self.lbl_status.configure(text="Error de ejecución", fg=ERROR_COLOR)
            self.btn_connect.configure(state=tk.NORMAL, bg=ACCENT_COLOR)
            messagebox.showerror("Error de Ejecución", f"Fallo al ejecutar RDP: {e}")

    def monitor_process(self, proc, log_path, log_file, elapsed_ms):
        ret = proc.poll()
        if ret is not None:
            # Process exited, close log file
            try:
                log_file.close()
            except Exception:
                pass
                
            self.btn_connect.configure(state=tk.NORMAL, bg=ACCENT_COLOR)
            
            if ret != 0:
                self.lbl_status.configure(text="Error de conexión", fg=ERROR_COLOR)
                # An error occurred. Show error window.
                try:
                    with open(log_path, "r") as f:
                        log_content = f.read().strip()
                except Exception:
                    log_content = "No se pudo leer el archivo de log."
                self.show_error_window(ret, log_content)
            else:
                self.lbl_status.configure(text="Conexión finalizada", fg=TEXT_MUTED)
                self.root.after(3000, lambda: self.lbl_status.configure(text=""))
            return
            
        if elapsed_ms < 3000:
            self.root.after(200, lambda: self.monitor_process(proc, log_path, log_file, elapsed_ms + 200))
        else:
            # We monitored for 3 seconds, assume it started successfully. Close file descriptor.
            try:
                log_file.close()
            except Exception:
                pass
            self.lbl_status.configure(text="Conexión iniciada", fg=SUCCESS_COLOR)
            self.btn_connect.configure(state=tk.NORMAL, bg=ACCENT_COLOR)
            self.root.after(5000, lambda: self.lbl_status.configure(text=""))

    def show_error_window(self, exit_code, log_content):
        err_win = tk.Toplevel(self.root)
        err_win.title("Error de Conexión RDP")
        err_win.geometry("600x400")
        err_win.configure(bg=BG_COLOR)
        err_win.transient(self.root)
        err_win.grab_set()
        
        lbl = tk.Label(err_win, text=f"La conexión falló (Código de salida: {exit_code})", font=("Arial", 12, "bold"), fg=ERROR_COLOR, bg=BG_COLOR, pady=10)
        lbl.pack()
        
        txt_frame = tk.Frame(err_win, bg=BG_COLOR, padx=10, pady=10)
        txt_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(txt_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        txt = tk.Text(txt_frame, font=("Courier", 10), fg=TEXT_COLOR, bg=SIDEBAR_BG, wrap=tk.WORD, yscrollcommand=scrollbar.set, bd=0)
        txt.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)
        
        txt.insert(tk.END, log_content)
        txt.config(state=tk.DISABLED)
        
        btn_close = tk.Button(err_win, text="Cerrar", font=("Arial", 10, "bold"), fg=TEXT_COLOR, bg=CARD_BG, bd=0, cursor="hand2", command=err_win.destroy, pady=6, width=10)
        btn_close.pack(pady=10)

    def install_desktop_shortcut(self):
        shortcut_path = os.path.expanduser("~/.local/share/applications/freerdp-launcher.desktop")
        bin_dir = os.path.expanduser("~/.local/bin")
        bin_path = os.path.join(bin_dir, "rdp-launcher")
        
        try:
            # Ensure directories exist
            os.makedirs(bin_dir, exist_ok=True)
            os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
            
            # Copy current script to ~/.local/bin/rdp-launcher
            import shutil
            current_script = os.path.abspath(sys.argv[0])
            shutil.copy2(current_script, bin_path)
            os.chmod(bin_path, 0o755)
            
            # Write desktop file
            desktop_content = f"""[Desktop Entry]
Name=sdl-freerdp3
Comment=FreeRDP SDL3 Remote Desktop Client (Custom Multimonitor Build)
Exec={bin_path}
Icon=preferences-desktop-remote
Terminal=false
Type=Application
Categories=Network;RemoteAccess;
StartupNotify=true
"""
            with open(shortcut_path, "w") as f:
                f.write(desktop_content)
                
            messagebox.showinfo("Éxito", "Acceso directo y binario del lanzador creados/reparados con éxito en su sistema.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo instalar el acceso directo: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = RDPLauncherApp(root)
    root.mainloop()
