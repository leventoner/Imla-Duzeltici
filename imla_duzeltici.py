import os
import sys
import time
import threading
import keyboard
import pyperclip
from mintlemon import Normalizer
import pystray
from PIL import Image
import tkinter as tk
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Global variables
click_count = 0
last_click_time = 0
COOLDOWN = 0.5 # Window for double/triple click
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
    
    # Use absolute path for debug file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    debug_path = os.path.join(current_dir, "debug_models.txt")
    
    try:
        # Use v1 for EEA/Belgium stability
        genai.configure(api_key=GEMINI_API_KEY)
        
        # Try to find what's actually available
        available_names = []
        try:
            available_models = list(genai.list_models())
            available_names = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
        except Exception as list_err:
            print(f"Model listeleme hatası: {list_err}")

        # Preferred models (Belgium/EEA appears to have 2.0 and 2.5 flash models)
        preferred_keywords = ['gemini-2.0-flash', 'gemini-2.1-flash', 'gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-pro']
        
        for kw in preferred_keywords:
            for full_name in available_names:
                if kw in full_name:
                    try:
                        print(f"Model basariyla secildi: {full_name}")
                        return genai.GenerativeModel(full_name)
                    except Exception as mod_err:
                        print(f"Model {full_name} baslatilamadi: {mod_err}")
                        continue
        
        # If no list match, try standard names one more time
        for fallback in ['gemini-1.5-flash', 'gemini-pro']:
            try:
                return genai.GenerativeModel(f"models/{fallback}")
            except:
                continue
                
        return None
        
    except Exception as e:
        print(f"Gemini kritik hata: {e}")
        return None

# Simple wrapper to check if model is valid before calling
def get_model():
    global model
    if model is None:
        model = initialize_gemini()
    return model

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

        title_label = tk.Label(
            frame, 
            text=self.title, 
            fg=self.color, 
            bg='#2c3e50',
            font=('Segoe UI', 10, 'bold')
        )
        title_label.pack(anchor='w')

        display_msg = self.message
        if len(display_msg) > 100:
            display_msg = display_msg[:97] + "..."
            
        msg_label = tk.Label(
            frame, 
            text=display_msg, 
            fg='white', 
            bg='#2c3e50',
            font=('Segoe UI', 9),
            wraplength=300,
            justify='left'
        )
        msg_label.pack(anchor='w', pady=(2, 0))

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
        overlay.after(5000, root.destroy)
        root.mainloop()

def show_notification(title, message, color='#3498db'):
    NotificationOverlay(title, message, color)

def deasciify_text(text):
    try:
        return Normalizer.deasciify(text)
    except Exception as e:
        print(f"Deasciify error: {e}")
        return text

def improve_text(text):
    # Get all available models to try if one fails
    available_model_names = []
    try:
        available_models = list(genai.list_models())
        available_model_names = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
    except:
        available_model_names = ['models/gemini-2.0-flash', 'models/gemini-1.5-flash', 'models/gemini-pro']

    # Current prioritized list based on your region
    prioritized = ['models/gemini-2.0-flash', 'models/gemini-2.5-flash', 'models/gemini-1.5-flash', 'models/gemini-pro']
    # Add any other available models that aren't in our priority list
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
            if "429" in error_msg:
                print(f"Model {model_name} kota hatası verdi (429), bir sonraki deneniyor...")
                continue
            elif "404" in error_msg:
                continue
            else:
                print(f"Model {model_name} hata verdi: {error_msg}")
                continue
    
    return f"Hata: Üzgünüm, şu an tüm modeller kota veya erişim hatası veriyor. (Son hata: {last_error})"

def process_action():
    global click_count
    current_clicks = click_count
    click_count = 0 # Reset immediately
    
    if not is_running:
        return

    # Wait a moment for the system to handle the copy action
    time.sleep(0.2)
    original_text = pyperclip.paste()
    
    if not original_text or not original_text.strip():
        return

    if current_clicks == 2:
        # Türkçe karakter düzeltme
        corrected = deasciify_text(original_text)
        if original_text != corrected:
            pyperclip.copy(corrected)
            show_notification("Karakterler Düzeltildi!", corrected, color='#2ecc71')
    
    elif current_clicks >= 3:
        # Metin iyileştirme (Improve)
        show_notification("İşleniyor...", "Metin yapay zeka ile iyileştiriliyor...", color='#9b59b6')
        improved = improve_text(original_text)
        
        if improved and not improved.startswith("ERROR") and not improved.startswith("Hata:"):
            pyperclip.copy(improved)
            show_notification("Yazı İyileştirildi!", improved, color='#9b59b6')
        else:
            show_notification("İşlem Başarısız", improved, color='#e74c3c')

def on_ctrl_c():
    global click_count, timer, last_click_time
    
    if not is_running:
        return
        
    current_time = time.time()
    
    # Check if this click is part of a sequence
    if current_time - last_click_time < COOLDOWN:
        click_count += 1
    else:
        click_count = 1
    
    last_click_time = current_time
    
    # Cancel previous timer if exists
    if timer:
        timer.cancel()
    
    # Set a timer to wait for more clicks
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
        pystray.MenuItem("İmla Düzeltici Durumu:", lambda: None, enabled=False),
        pystray.MenuItem("  2x Ctrl+C: Karakter Düzelt", lambda: None, enabled=False),
        pystray.MenuItem("  3x Ctrl+C: Metni İyileştir", lambda: None, enabled=False),
        pystray.MenuItem("---", lambda: None, enabled=False),
        pystray.MenuItem("Çıkış", quit_app)
    )
    icon = pystray.Icon("imla_duzeltici", image, "İmla Düzeltici & Yazı İyileştirici", menu)
    icon.run()

def start_listener():
    # Use suppress=False to allow Ctrl+C to still perform normal copy
    keyboard.add_hotkey('ctrl+c', on_ctrl_c)
    while is_running:
        time.sleep(1)

if __name__ == "__main__":
    # Start keyboard listener
    threading.Thread(target=start_listener, daemon=True).start()

    # Initial notification
    msg = "Uygulama çalışıyor!\n2x Ctrl+C: Karakter\n3x Ctrl+C: İyileştir"
    show_notification("İmla Düzeltici v2.0", msg)

    # Start tray
    setup_tray()
