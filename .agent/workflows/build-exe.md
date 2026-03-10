---
description: Yeni bir EXE dosyası oluşturma rehberi
---

Bu workflow, İmla Düzeltici uygulamasını güncellediğinizde veya tekrar EXE haline getirmek istediğinizde izlemeniz gereken adımları içerir.

### Ön Gereksinimler
Terminalin proje dizininde (`c:\Users\lener\Desktop\code\Python\imla duzeltici`) açık olduğundan emin olun.

### Adımlar

1. **Çalışan Uygulamayı Kapatın**:
Eğer uygulama şu an çalışıyorsa, EXE'nin üzerine yazabilmek için kapatmalısınız:
```powershell
taskkill /F /IM imla_duzeltici.exe /T 2>$null
```

2. **Sanal Ortamı Aktif Edin**:
```powershell
.\venv\Scripts\activate
```

2. **EXE Oluşturma Komutunu Çalıştırın**:
Aşağıdaki komut, tüm bağımlılıkları ve veri dosyalarını tek bir EXE dosyasına paketle ve ikon ekler:

// turbo
```powershell
pyinstaller --noconsole --onefile --add-data "icon.png;." --add-data ".env;." --add-data "settings.json;." --icon="icon.ico" --collect-all zeyrek --collect-all mintlemon --collect-all google.generativeai --name "imla_duzeltici" imla_duzeltici.py
```

3. **Sonuç**:
İşlem bittiğinde yeni EXE dosyanız `dist/imla_duzeltici.exe` konumunda hazır olacaktır.

**Not**: `build` klasörü ve `.spec` dosyası işlem sırasında geçici olarak oluşur, işlem bittikten sonra güvenle silebilirsiniz.
