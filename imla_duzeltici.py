import os
import sys
import time
import threading
import json
import keyboard
import pyperclip
from mintlemon import Normalizer
import pystray
from PIL import Image
import tkinter as tk
import ctypes
from ctypes import wintypes
from math import hypot
try:
    from pynput import mouse, keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    mouse = None
    pynput_keyboard = None
    HAS_PYNPUT = False
from dotenv import load_dotenv

# Helper functions for paths
def resource_path(relative_path):
    """ Get absolute path to internal bundled resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_external_path(relative_path):
    """ Get absolute path to file in the same directory as the executable """
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Load environment variables
# 1. Load from bundled .env (Internal default)
internal_env = resource_path(".env")
if os.path.exists(internal_env):
    load_dotenv(internal_env)

# 2. Load from external .env (User override)
external_env = get_external_path(".env")
if os.path.exists(external_env):
    load_dotenv(external_env, override=True)

# Settings logic
DEFAULT_SETTINGS = {
    "hotkey": "ctrl+c",
    "cooldown": 0.5,
    "notify_on_no_change": True,
    "floating_icon": True
}

def load_settings():
    # Try external settings first (user modifiable)
    settings_path = get_external_path("settings.json")
    
    # If external doesn't exist, try internal bundled default
    if not os.path.exists(settings_path):
        settings_path = resource_path("settings.json")
        
    try:
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception as e:
        print(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS

settings = load_settings()

# Global variables
click_count = 0
last_click_time = 0
COOLDOWN = settings["cooldown"]
is_running = True
processing_lock = threading.Lock()
timer = None
ignore_hotkeys = False

# Gemini configuration
import google.generativeai as genai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def initialize_gemini():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not found in environment.")
        return None
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        available_names = []
        try:
            available_models = list(genai.list_models())
            available_names = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
        except Exception as list_err:
            print(f"Model listeleme hatası: {list_err}")

        preferred_keywords = ['gemini-2.0-flash', 'gemini-2.1-flash', 'gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-pro']
        for kw in preferred_keywords:
            for full_name in available_names:
                if kw in full_name:
                    return genai.GenerativeModel(full_name)
        
        for fallback in ['gemini-1.5-flash', 'gemini-pro']:
            try:
                return genai.GenerativeModel(f"models/{fallback}")
            except:
                continue
        return None
    except Exception as e:
        print(f"Gemini kritik hata: {e}")
        return None

model = initialize_gemini()

# The resource_path and get_external_path functions are moved to the top

# Global UI Thread for Notifications and Menus
ui_root = None
ui_ready = threading.Event()

def run_ui_thread():
    global ui_root
    ui_root = tk.Tk()
    ui_root.withdraw()
    ui_ready.set()
    ui_root.mainloop()

threading.Thread(target=run_ui_thread, daemon=True).start()
ui_ready.wait()

class NotificationOverlay:
    def __init__(self, title, message, color='#3498db'):
        self.title = title
        self.message = message
        self.color = color
        # Call UI creation in the main UI thread
        ui_root.after(0, self._create_overlay)

    def _create_overlay(self):
        overlay = tk.Toplevel(ui_root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.0)
        overlay.configure(bg='#2c3e50', highlightbackground=self.color, highlightthickness=2)
        
        frame = tk.Frame(overlay, bg='#2c3e50', padx=15, pady=10)
        frame.pack()

        tk.Label(frame, text=self.title, fg=self.color, bg='#2c3e50', font=('Segoe UI', 10, 'bold')).pack(anchor='w')

        display_msg = self.message
        if len(display_msg) > 120:
            display_msg = display_msg[:117] + "..."
            
        tk.Label(frame, text=display_msg, fg='white', bg='#2c3e50', font=('Segoe UI', 9), wraplength=400, justify='left').pack(anchor='w', pady=(2, 0))

        overlay.update_idletasks()
        width = overlay.winfo_width()
        height = overlay.winfo_height()
        screen_width = overlay.winfo_screenwidth()
        screen_height = overlay.winfo_screenheight()
        
        x = screen_width - width - 20
        y = screen_height - height - 60
        overlay.geometry(f"+{x}+{y}")

        def fade_in():
            try:
                alpha = overlay.attributes("-alpha")
                if alpha < 0.95:
                    overlay.attributes("-alpha", alpha + 0.1)
                    overlay.after(30, fade_in)
            except: pass
        
        fade_in()
        
        def close():
            try:
                overlay.destroy()
            except: pass
            
        overlay.after(4000, close)

def show_notification(title, message, color='#3498db'):
    NotificationOverlay(title, message, color)

class FloatingMenu(tk.Toplevel):
    def __init__(self, x, y, on_fix, on_tr, on_auto):
        super().__init__(ui_root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.configure(bg='#2c3e50')
        
        # Geometry: Pill shaped for 3 items + tooltip space
        width, height = 150, 62
        self.geometry(f"{width}x{height}+{x+5}+{y-20}")
        self.x_range = (x+5, x+5+width)
        self.y_range = (y-20, y-20+height)
        
        self.canvas = tk.Canvas(self, width=width, height=height, bg='#2c3e50', highlightthickness=0)
        self.canvas.pack()
        
        # Draw rounded background (pill shape at bottom)
        self._draw_pill(self.canvas, width, 42, '#34495e', '#2c3e50', y_off=20)
        
        # Tooltip Label
        self.tooltip = tk.Label(self, text="", fg='#3498db', bg='#2c3e50', font=('Segoe UI', 9, 'bold'))
        self.tooltip.place(x=0, y=0, width=150)

        # Buttons
        def hover_eff(btn, color, text):
            def on_enter(e):
                btn.config(bg=color)
                self.tooltip.config(text=text, fg=color)
            def on_leave(e):
                btn.config(bg='#34495e')
                self.tooltip.config(text="")
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)

        # Labels as Buttons (to avoid focus theft entirely)
        self.btn_fix = tk.Label(self, text="📝", font=('Segoe UI Emoji', 13), 
                           bg='#34495e', fg='white', cursor='hand2')
        self.btn_tr = tk.Label(self, text="🇹🇷", font=('Segoe UI Emoji', 12), 
                           bg='#34495e', fg='white', cursor='hand2')
        self.btn_auto = tk.Label(self, text="✨", font=('Segoe UI Emoji', 13), 
                           bg='#34495e', fg='white', cursor='hand2')
        
        self.btn_fix.place(x=10, y=26, width=40, height=30)
        self.btn_tr.place(x=55, y=26, width=40, height=30)
        self.btn_auto.place(x=100, y=26, width=40, height=30)
        
        # Helper to bind hover and click
        def bind_events(lbl, color, text, command):
            def on_enter(e):
                lbl.config(bg=color)
                self.tooltip.config(text=text, fg=color)
            def on_leave(e):
                lbl.config(bg='#34495e')
                self.tooltip.config(text="")
            def on_click(e):
                command()
                
            lbl.bind("<Enter>", on_enter)
            lbl.bind("<Leave>", on_leave)
            lbl.bind("<Button-1>", on_click)

        bind_events(self.btn_fix, '#2ecc71', "Karakter Düzelt", on_fix)
        bind_events(self.btn_tr, '#3498db', "Türkçe İyileştir", on_tr)
        bind_events(self.btn_auto, '#9b59b6', "Orijinal Dilde", on_auto)
        
        self.after(100, self.fade_in)
        
        # Windows-specific: Make the window not take focus when clicked (preserving selection)
        self.after(100, self._make_no_activate)

    def _make_no_activate(self):
        # Constants for Windows API
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        
        try:
            # winfo_id() is the correct handle for Toplevel
            hwnd = self.winfo_id()
            current_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current_style | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
        except Exception as e:
            print(f"Error setting no-activate style: {e}")

    def _draw_pill(self, canvas, w, h, color, shadow, y_off=0):
        r = h // 2
        canvas.create_oval(2, y_off+2, h-2, y_off+h-2, fill=color, outline=color)
        canvas.create_oval(w-h+2, y_off+2, w-2, y_off+h-2, fill=color, outline=color)
        canvas.create_rectangle(r, y_off+2, w-r, y_off+h-2, fill=color, outline=color)

    def fade_in(self):
        try:
            alpha = self.attributes("-alpha")
            if alpha < 0.98:
                self.attributes("-alpha", alpha + 0.15)
                self.after(20, self.fade_in)
        except: pass

    def destroy_with_fade(self):
        try:
            alpha = self.attributes("-alpha")
            if alpha > 0.1:
                self.attributes("-alpha", alpha - 0.15)
                self.after(20, self.destroy_with_fade)
            else:
                self.destroy()
        except:
            pass

    def is_inside(self, x, y):
        try:
            return (self.x_range[0] <= x <= self.x_range[1] and 
                    self.y_range[0] <= y <= self.y_range[1])
        except: return False

class MouseTracker:
    def __init__(self, settings, fix_callback, improve_callback):
        self.settings = settings
        self.fix_callback = fix_callback
        self.improve_callback = improve_callback
        self.start_pos = (0, 0)
        self.active_menu = None
        self.listener = None

    def on_click(self, x, y, button, pressed):
        if not HAS_PYNPUT or not self.settings.get("floating_icon", True):
            return
            
        if pressed:
            if self.active_menu:
                if not self.active_menu.is_inside(x, y):
                    ui_root.after(0, self.active_menu.destroy_with_fade)
                    self.active_menu = None
            self.start_pos = (x, y)
        else:
            dist = hypot(x - self.start_pos[0], y - self.start_pos[1])
            if dist > 20: 
                # Check for I-Beam cursor to be sure it's a text selection
                class CURSORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong), ("flags", ctypes.c_ulong), ("hCursor", ctypes.c_void_p), ("pt", ctypes.c_long * 2)]
                ci = CURSORINFO()
                ci.cbSize = ctypes.sizeof(CURSORINFO)
                ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci))
                
                # h_ibeam = 65541 or similar, but checking if it's non-standard is enough often
                # For now, distance check + a tiny bit of verification
                time.sleep(0.05)
                self.show_menu(x, y)

    def show_menu(self, x, y):
        # We must create UI in the UI thread
        ui_root.after(0, lambda: self._create_menu(x, y))

    def _create_menu(self, x, y):
        # Destroy existing menu
        if self.active_menu:
            try: self.active_menu.destroy()
            except: pass
            
        def trigger_fix():
            self._copy_and_run(self.fix_callback)

        def trigger_tr():
            self._copy_and_run(lambda: handle_improve_clipboard(auto_detect=False))

        def trigger_auto():
            self._copy_and_run(self.improve_callback)

        self.active_menu = FloatingMenu(x, y, trigger_fix, trigger_tr, trigger_auto)

    def _copy_and_run(self, callback):
        global ignore_hotkeys
        if self.active_menu:
            ui_root.after(0, self.active_menu.destroy)
            self.active_menu = None
            
        def worker():
            global ignore_hotkeys
            time.sleep(0.2)
            ignore_hotkeys = True
            
            try:
                # Clear clipboard first to detect fresh copy
                try: pyperclip.copy("")
                except: pass
                
                # Try to copy multiple times if needed (some apps are slow)
                for _ in range(3):
                    keyboard.press_and_release('ctrl+c')
                    # Wait and check
                    for _ in range(5):
                        time.sleep(0.1)
                        try:
                            if pyperclip.paste().strip():
                                break
                        except: pass
                    if pyperclip.paste().strip(): break
                
                callback()
            finally:
                time.sleep(0.5)
                ignore_hotkeys = False
            
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        if not HAS_PYNPUT:
            print("pynput not available, floating icon disabled.")
            return
        try:
            self.listener = mouse.Listener(on_click=self.on_click)
            self.listener.start()
        except Exception as e:
            print(f"Mouse listener error: {e}")

def check_lib_health():
    try:
        return Normalizer.deasciify("kiymetli") == "kıymetli"
    except:
        return False

def deasciify_text(text):
    if not text:
        return text
    try:
        # 1. Full text deasciify
        corrected = Normalizer.deasciify(text)
        
        # 2. Word-by-word fallback (sometimes more reliable for mixed texts)
        # Use regex or split() to handle all whitespace types
        words = text.split()
        if not words: return corrected
        
        corrected_words = [Normalizer.deasciify(w) for w in words]
        
        # We need to preserve original spacing if possible, but for comparison:
        # if the word-by-word produced a different result than full-text, 
        # it might be better. 
        # However, Normalizer usually does a good job. 
        # Let's check if the current 'corrected' still has 'kiymetli' or 'umarim'
        
        problematic_words = ["kiymetli", "umarim", "basarilar", "gormek"]
        for p in problematic_words:
            if p in corrected and p not in text: # This shouldn't happen, but logic check
                pass
            if p in text and p in corrected:
                # Full text failed to catch this word, try word-by-word results
                # Simple replacement for better accuracy
                for i, w in enumerate(words):
                    if w in problematic_words or any(c in "cgiosu" for c in w.lower()):
                         # This is a bit complex, let's just return the best version we found
                         pass
        
        # Simplest: if word by word changed something that full text didn't, or vice-versa
        # Let's just return the most 'turkish' looking one (more non-ascii chars)
        # Reconstruct with original spacing for comparison
        reconstructed = text
        for i, w in enumerate(words):
            cw = corrected_words[i]
            if cw != w:
                reconstructed = reconstructed.replace(w, cw, 1)

        def count_turkish(s):
            return sum(1 for c in s if c in "çğıöşüÇĞİÖŞÜ")
            
        if count_turkish(corrected) < count_turkish(reconstructed):
            corrected = reconstructed

        return corrected
    except Exception as e:
        print(f"Deasciify error: {e}")
        return text

def improve_text(text, auto_detect=False):
    try:
        available_models = list(genai.list_models())
        available_model_names = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
    except:
        available_model_names = ['models/gemini-2.0-flash', 'models/gemini-1.5-flash', 'models/gemini-pro']

    prioritized = ['models/gemini-2.0-flash', 'models/gemini-2.5-flash', 'models/gemini-1.5-flash', 'models/gemini-pro']
    for m in available_model_names:
        if m not in prioritized:
            prioritized.append(m)

    last_error = ""
    for model_name in prioritized:
        try:
            current_model = genai.GenerativeModel(model_name)
            if auto_detect:
                prompt = f"Improve the grammar, spelling, word order, and general flow of the following text in its original language. Return only the corrected text, do not add any explanations or comments. Text: {text}"
            else:
                prompt = f"Aşağıdaki Türkçe metni dilbilgisi, imla, kelime sırası ve genel akıcılık açısından iyileştir. Sadece düzeltilmiş metni döndür, başka hiçbir şey yazma. Metin: {text}"
            
            response = current_model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            continue
    return f"Hata: {last_error}"


def handle_fix_clipboard():
    # If the hotkey is ctrl+c, the user's clicks already put the text in the clipboard
    # We just need to wait a tiny bit to make sure OS finished the write
    time.sleep(0.3)
    
    # Try to get text from clipboard with retries
    text = ""
    for i in range(10):
        try:
            text = pyperclip.paste()
            if text and len(text.strip()) > 0: 
                break
        except:
            pass
        time.sleep(0.1)

    if not text or not text.strip():
        show_notification("Hata", "Lütfen metni seçin ve tekrar deneyin.", color='#e74c3c')
        return
    
    corrected = deasciify_text(text)
    
    if text.strip() != corrected.strip():
        pyperclip.copy(corrected)
        show_notification("Karakterler Düzeltildi!", corrected, color='#2ecc71')
    else:
        # Check if library is actually alive
        if not check_lib_health():
             show_notification("Kritik Hata", "Dil kütüphanesi (Normalizer) çalışmıyor. Lütfen uygulamayı yönetici olarak başlatmayı veya yeniden kurmayı deneyin.", color='#e67e22')
        elif settings.get("notify_on_no_change", True):
            show_notification("Düzeltme Gerekmedi", "Metin zaten düzgün görünüyor veya düzeltilecek karakter bulunamadı.", color='#3498db')

def handle_improve_clipboard(auto_detect=False):
    # If hotkey is ctrl+c, we don't send it again
    if settings['hotkey'].lower() != 'ctrl+c':
        keyboard.press_and_release('ctrl+c')
    
    time.sleep(0.3)
    
    text = ""
    for i in range(10):
        try:
            text = pyperclip.paste()
            if text and len(text.strip()) > 0: break
        except:
            pass
        time.sleep(0.1)

    if not text or not text.strip():
        show_notification("Hata", "Lütfen metni seçin ve tekrar deneyin.", color='#e74c3c')
        return
    
    status_msg = "Metin kendi dilinde iyileştiriliyor..." if auto_detect else "Metin yapay zeka ile iyileştiriliyor..."
    show_notification("İşleniyor...", status_msg, color='#9b59b6')
    improved = improve_text(text, auto_detect=auto_detect)
    
    if improved and not improved.startswith("Hata:"):
        pyperclip.copy(improved)
        success_title = "Dilde İyileştirildi!" if auto_detect else "Yazı İyileştirildi!"
        show_notification(success_title, improved, color='#9b59b6')
    else:
        show_notification("İşlem Başarısız", improved, color='#e74c3c')

def process_action():
    global click_count
    current_clicks = click_count
    click_count = 0
    
    if not is_running: return

    # Wait a moment for the system to handle the copy action
    time.sleep(0.3)
    
    if current_clicks == 2:
        handle_fix_clipboard()
    elif current_clicks == 3:
        handle_improve_clipboard(auto_detect=False)
    elif current_clicks >= 4:
        handle_improve_clipboard(auto_detect=True)

def on_hotkey_pressed():
    global click_count, timer, last_click_time
    if not is_running or ignore_hotkeys: return
        
    current_time = time.time()
    if current_time - last_click_time < COOLDOWN:
        click_count += 1
    else:
        click_count = 1
    
    last_click_time = current_time
    if timer: timer.cancel()
    timer = threading.Timer(COOLDOWN, process_action)
    timer.start()

def quit_app(icon, item):
    global is_running
    is_running = False
    icon.stop()
    os._exit(0)

def toggle_setting(key):
    settings[key] = not settings.get(key, True)
    # Save to external settings
    settings_path = get_external_path("settings.json")
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

def setup_tray():
    image = Image.open(resource_path("icon.png"))
    menu = pystray.Menu(
        pystray.MenuItem("İmla Düzeltici Durumu", lambda: None, enabled=False),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem("Panoyu Düzelt (Karakter)", handle_fix_clipboard),
        pystray.MenuItem("Panoyu İyileştir (Türkçe)", lambda: handle_improve_clipboard(auto_detect=False)),
        pystray.MenuItem("Panoyu İyileştir (Kendi Dili)", lambda: handle_improve_clipboard(auto_detect=True)),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem("Seçim İkonunu Göster" + ("" if HAS_PYNPUT else " (Kütüphane Eksik)"), 
                         lambda icon, item: toggle_setting("floating_icon"),
                         checked=lambda item: settings.get("floating_icon", True),
                         enabled=HAS_PYNPUT),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem(f"Kısayol: {settings['hotkey'].upper()}", lambda: None, enabled=False),
        pystray.MenuItem(f"  2x {settings['hotkey'].upper()}: Karakter", lambda: None, enabled=False),
        pystray.MenuItem(f"  3x {settings['hotkey'].upper()}: Türkçe İyileştir", lambda: None, enabled=False),
        pystray.MenuItem(f"  4x {settings['hotkey'].upper()}: Dilde İyileştir", lambda: None, enabled=False),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem("Çıkış", quit_app)
    )
    icon = pystray.Icon("imla_duzeltici", image, "İmla Düzeltici & Yazı İyileştirici", menu)
    icon.run()

def start_listener():
    try:
        keyboard.add_hotkey(settings['hotkey'], on_hotkey_pressed, suppress=False)
        while is_running:
            time.sleep(1)
    except Exception as e:
        print(f"Hotkey error: {e}")

if __name__ == "__main__":
    # Command line arguments handling
    if len(sys.argv) > 1:
        if "--fix" in sys.argv:
            handle_fix_clipboard()
            sys.exit(0)
        elif "--improve" in sys.argv:
            handle_improve_clipboard()
            sys.exit(0)

    # Start keyboard listener
    threading.Thread(target=start_listener, daemon=True).start()

    # Start mouse listener for floating icon
    mouse_tracker = MouseTracker(settings, handle_fix_clipboard, lambda: handle_improve_clipboard(auto_detect=True))
    mouse_tracker.start()

    # Initial notification and library health check
    msg = f"Uygulama hazır!\n2x {settings['hotkey'].upper()}: Karakter\n3x {settings['hotkey'].upper()}: Türkçe İyileştir\n4x {settings['hotkey'].upper()}: Kendi Dilinde"
    if not check_lib_health():
        msg += "\n\n⚠️ KRİTİK: Dil kütüphanesi yüklenemedi!"
        show_notification("İmla Düzeltici v2.2 - HATA", msg, color='#e67e22')
    else:
        show_notification("İmla Düzeltici v2.2", msg)

    # Start tray
    setup_tray()
