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
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Settings logic
DEFAULT_SETTINGS = {
    "hotkey": "ctrl+c",
    "cooldown": 0.5,
    "notify_on_no_change": True
}

def load_settings():
    try:
        if os.path.exists("settings.json"):
            with open("settings.json", "r", encoding="utf-8") as f:
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

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class NotificationOverlay:
    def __init__(self, title, message, color='#3498db'):
        self.title = title
        self.message = message
        self.color = color
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        root = tk.Tk()
        root.withdraw()
        
        overlay = tk.Toplevel(root)
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
            alpha = overlay.attributes("-alpha")
            if alpha < 0.95:
                overlay.attributes("-alpha", alpha + 0.1)
                overlay.after(30, fade_in)
        
        fade_in()
        overlay.after(4000, root.destroy)
        root.mainloop()

def show_notification(title, message, color='#3498db'):
    NotificationOverlay(title, message, color)

def deasciify_text(text):
    if not text:
        return text
    try:
        # Try full text first
        corrected = Normalizer.deasciify(text)
        
        # If no change detected, try word by word (sometimes more effective for short/dense ASCII)
        if corrected == text:
            words = text.split(' ')
            corrected_words = []
            for word in words:
                if word:
                    # Basic check: if word has only ascii but no turkish
                    corrected_words.append(Normalizer.deasciify(word))
                else:
                    corrected_words.append('')
            corrected = ' '.join(corrected_words)
            
        return corrected
    except Exception as e:
        print(f"Deasciify error: {e}")
        return text

def improve_text(text):
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
            prompt = f"Aşağıdaki Türkçe metni dilbilgisi, imla, kelime sırası ve genel akıcılık açısından iyileştir. Sadece düzeltilmiş metni döndür, başka hiçbir şey yazma. Metin: {text}"
            response = current_model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            continue
    return f"Hata: {last_error}"

def handle_fix_clipboard():
    # 1. Force a copy of selected text (simulating Ctrl+C)
    # This is important because the user's manual Ctrl+C might still be in progress
    keyboard.press_and_release('ctrl+c')
    time.sleep(0.4) # Wait for OS to put text in clipboard

    # 2. Try to get text from clipboard with retries
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
        if settings.get("notify_on_no_change", True):
            show_notification("Düzeltme Gerekmedi", "Metin zaten düzgün görünüyor.", color='#3498db')

def handle_improve_clipboard():
    keyboard.press_and_release('ctrl+c')
    time.sleep(0.4)
    
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
    
    show_notification("İşleniyor...", "Metin yapay zeka ile iyileştiriliyor...", color='#9b59b6')
    improved = improve_text(text)
    
    if improved and not improved.startswith("Hata:"):
        pyperclip.copy(improved)
        show_notification("Yazı İyileştirildi!", improved, color='#9b59b6')
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
    elif current_clicks >= 3:
        handle_improve_clipboard()

def on_hotkey_pressed():
    global click_count, timer, last_click_time
    if not is_running: return
        
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

def setup_tray():
    image = Image.open(resource_path("icon.png"))
    menu = pystray.Menu(
        pystray.MenuItem("İmla Düzeltici Durumu", lambda: None, enabled=False),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem("Panoyu Düzelt (Karakter)", handle_fix_clipboard),
        pystray.MenuItem("Panoyu İyileştir (Yapay Zeka)", handle_improve_clipboard),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem(f"Kısayol: {settings['hotkey'].upper()}", lambda: None, enabled=False),
        pystray.MenuItem(f"  2x {settings['hotkey'].upper()}: Karakter", lambda: None, enabled=False),
        pystray.MenuItem(f"  3x {settings['hotkey'].upper()}: İyileştir", lambda: None, enabled=False),
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

    # Initial notification
    msg = f"Uygulama hazır!\n2x {settings['hotkey'].upper()}: Düzelt\n3x {settings['hotkey'].upper()}: İyileştir"
    show_notification("İmla Düzeltici v2.1", msg)

    # Start tray
    setup_tray()
