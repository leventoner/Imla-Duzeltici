import sys
import os
import winreg as reg

def add_context_menu():
    # Get the path of the executable or current script
    if getattr(sys, 'frozen', False):
        app_path = sys.executable
    else:
        app_path = f'"{sys.executable}" "{os.path.abspath("imla_duzeltici.py")}"'

    # Registry key paths
    # We add to HKEY_CLASSES_ROOT\* which applies to all files
    # And HKEY_CLASSES_ROOT\Directory\Background which applies to folder backgrounds
    
    try:
        # 1. Characters Fix
        base_key = r"*\shell\ImlaDuzeltici_Fix"
        with reg.CreateKey(reg.HKEY_CLASSES_ROOT, base_key) as key:
            reg.SetValue(key, "", reg.REG_SZ, "İmla Düzeltici: Karakterleri Düzelt")
            reg.SetValueEx(key, "Icon", 0, reg.REG_SZ, app_path.replace('"', ''))
        
        with reg.CreateKey(reg.HKEY_CLASSES_ROOT, base_key + r"\command") as key:
            reg.SetValue(key, "", reg.REG_SZ, f'{app_path} --fix')

        # 2. Text Improve
        base_key = r"*\shell\ImlaDuzeltici_Improve"
        with reg.CreateKey(reg.HKEY_CLASSES_ROOT, base_key) as key:
            reg.SetValue(key, "", reg.REG_SZ, "İmla Düzeltici: Metni İyileştir")
            reg.SetValueEx(key, "Icon", 0, reg.REG_SZ, app_path.replace('"', ''))
        
        with reg.CreateKey(reg.HKEY_CLASSES_ROOT, base_key + r"\command") as key:
            reg.SetValue(key, "", reg.REG_SZ, f'{app_path} --improve')

        print("Windows Sağ Tık Menüsü başarıyla eklendi!")
        print("Not: Bu menü dosyalar üzerinde sağ tıkladığınızda görünür.")
    except Exception as e:
        print(f"Hata: Kayıt defteri güncellenemedi. {e}")
        print("Lütfen terminali Yönetici olarak çalıştırın.")

if __name__ == "__main__":
    add_context_menu()
