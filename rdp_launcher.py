#!/usr/bin/env python3
import os
import sys
import json
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

def load_profiles():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_profiles(profiles):
    try:
        with open(PROFILES_FILE, "w") as f:
            json.dump(profiles, f, indent=4)
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
        self.val_user.set(data.get("user", ""))
        self.val_pass.set(data.get("pass", ""))
        self.val_domain.set(data.get("domain", ""))
        self.val_multimon.set(data.get("multimon", True))
        self.val_fullscreen.set(data.get("fullscreen", True))
        self.val_audio.set(data.get("audio", True))
        self.val_clipboard.set(data.get("clipboard", True))
        
        self.btn_delete.configure(state=tk.NORMAL, bg=ERROR_COLOR)

    def new_profile(self):
        self.current_profile_name = None
        for btn in self.profile_buttons.values():
            btn.configure(bg=SIDEBAR_BG, font=("Arial", 11))
            
        self.val_name.set("Nuevo Perfil")
        self.val_host.set("")
        self.val_user.set("")
        self.val_pass.set("")
        self.val_domain.set("")
        self.val_multimon.set(True)
        self.val_fullscreen.set(True)
        self.val_audio.set(True)
        self.val_clipboard.set(True)
        
        self.btn_delete.configure(state=tk.DISABLED, bg="#475569")

    def setup_main_panel(self):
        # Header
        lbl_head = tk.Label(self.main_panel, text="Detalles de la Conexión", font=("Arial", 18, "bold"), fg=TEXT_COLOR, bg=BG_COLOR)
        lbl_head.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))

        # Variables
        self.val_name = tk.StringVar()
        self.val_host = tk.StringVar()
        self.val_user = tk.StringVar()
        self.val_pass = tk.StringVar()
        self.val_domain = tk.StringVar()
        self.val_multimon = tk.BooleanVar(value=True)
        self.val_fullscreen = tk.BooleanVar(value=True)
        self.val_audio = tk.BooleanVar(value=True)
        self.val_clipboard = tk.BooleanVar(value=True)

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
        add_field(2, "Host / IP:", self.val_host)
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

        # Actions Panel (Save, Delete, Connect)
        actions_frame = tk.Frame(self.main_panel, bg=BG_COLOR)
        actions_frame.grid(row=8, column=0, columnspan=3, sticky="we", pady=(30, 0))

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

        # BIG Connect Button
        btn_connect = tk.Button(actions_frame, text="CONECTAR", font=("Arial", 12, "bold"), fg=TEXT_COLOR, bg=ACCENT_COLOR,
                                activeforeground=TEXT_COLOR, activebackground=ACCENT_HOVER, bd=0, cursor="hand2",
                                command=self.connect_rdp, padx=25, pady=8)
        btn_connect.pack(side=tk.RIGHT)
        btn_connect.bind("<Enter>", lambda e: btn_connect.configure(bg=ACCENT_HOVER))
        btn_connect.bind("<Leave>", lambda e: btn_connect.configure(bg=ACCENT_COLOR))

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
            "user": user,
            "pass": password,
            "domain": domain,
            "multimon": self.val_multimon.get(),
            "fullscreen": self.val_fullscreen.get(),
            "audio": self.val_audio.get(),
            "clipboard": self.val_clipboard.get()
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
        cmd = [binary, f"/v:{host}"]
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

        # Launch asynchronously so GUI doesn't hang
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            messagebox.showerror("Error de Ejecución", f"Fallo al ejecutar RDP: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = RDPLauncherApp(root)
    root.mainloop()
