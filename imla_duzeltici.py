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
        def count_turkish(s):
            return sum(1 for c in s if c in "çğıöşüÇĞİÖŞÜ")
            
        if count_turkish(corrected) < count_turkish(' '.join(corrected_words)):
            # Reconstruct with original spacing is hard with simple split, 
            # but let's try a better approach:
            new_text = text
            for i, w in enumerate(words):
                cw = corrected_words[i]
                if cw != w:
                    new_text = new_text.replace(w, cw, 1)
            corrected = new_text

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
        if settings.get("notify_on_no_change", True):
            # Double check: maybe it's the case where Normalizer failed to load inside EXE
            show_notification("Düzeltme Gerekmedi", "Metin zaten düzgün görünüyor.", color='#3498db')

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
        pystray.MenuItem("Panoyu İyileştir (Türkçe)", lambda: handle_improve_clipboard(auto_detect=False)),
        pystray.MenuItem("Panoyu İyileştir (Kendi Dili)", lambda: handle_improve_clipboard(auto_detect=True)),
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

    # Initial notification and library health check
    msg = f"Uygulama hazır!\n2x {settings['hotkey'].upper()}: Karakter\n3x {settings['hotkey'].upper()}: Türkçe İyileştir\n4x {settings['hotkey'].upper()}: Kendi Dilinde"
    if not check_lib_health():
        msg += "\n\n⚠️ KRİTİK: Dil kütüphanesi yüklenemedi!"
        show_notification("İmla Düzeltici v2.2 - HATA", msg, color='#e67e22')
    else:
        show_notification("İmla Düzeltici v2.2", msg)

    # Start tray
    setup_tray()
