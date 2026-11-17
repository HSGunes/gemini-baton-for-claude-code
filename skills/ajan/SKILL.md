---
name: ajan
description: Gemini alt ajanı (agy CLI üzerinde `baton` aracı, eski adı `ajan`). Uygulama işini Gemini'ye devretmek, durumunu izlemek, aynı konuşmada düzeltme istemek ve sonucu doğrulamak için kullan. Kullanıcı "geminiye ver", "hydrogen'e ver", "flash'a ver", "alt ajana ver", "delege et", "delegate to Gemini", "give this to Gemini", "hand off to a sub-agent", "use hydrogen", "use Gemini for implementation" dediğinde ya da büyük/tekrarlı uygulama işinde.
---

# ajan — Gemini alt ajanı ile çalışma

`baton` komutu (eski adı `ajan`) `PATH` üzerinde olmalı: eklentinin `bin/baton` dosyası `~/.local/bin/baton`'a bağlanır (README → Quick start) ya da `pip install .`. `command -v baton` boşsa kullanıcıya bağlamayı söyle. Doğrudan `agy` CLI'ı
`stream-json` ile çağırır. Rol paylaşımı: **Claude planlar, görev tanımını ve kabul ölçütlerini yazar,
testleri çalıştırır, denetler; ajan uygular.**

Tüm döngüyü ana bağlamı harcamadan yürütmek için `baton:ajan-yonetici` alt ajanını kullan
(ya da kullanıcı `/baton:devret <iş>` der). Aşağıdaki akış, döngüyü elle yürütmek içindir.

## Model seçimi
- Varsayılan `hydrogen` (`gemini-4-hydrogen-xhigh`, `--model` verilmezse kullanılır): çoğu iş. Diğer seçenekler: `hydrogen-high`, `hydrogen-orta`.
- `--model flash-orta` (`gemini-3.8-flash-medium`): basit, mekanik işler (daha az thinking token).
- `--model argon` (`gemini-4-argon-high`, ayrıca `argon-orta`, `flash`): alternatif modeller.
- Kullanıcı aksini söylemedikçe varsayılan `hydrogen` kullanılır (özel durum olmadıkça `--model` verme).

## Akış
1. **Görev dosyası yaz** (`GOREV_X.md`): bağlam (ilgili dosyaları OKU de), arayüz/imzalar, davranış,
   kabul ölçütleri, test beklentileri, "başka dosyaya dokunma". Teşhis ettiysen teşhisi yaz.
   Ortak bağlam varsa ayrı dosya ve `-g ORTAK.md -g GOREV_X.md` (veya `-g ORTAK.md GOREV_X.md`). Örnek: eklentinin `examples/GOREV_ORNEK.md`.
2. **Başlat** (arka planda, hemen döner):
   `baton baslat ETIKET -g GOREV_X.md --yaz DIZIN1 --yaz DIZIN2 [--oku DIZIN]`
   (her dizin için `--yaz` / `--oku` bayrağı tekrarlanır; farklı model gerekirse `--model ...`).
   - Etiket kuralı: `ETIKET` yalnız `[A-Za-z0-9._-]` karakterlerinden oluşabilir ve 1–64 karakter olmalıdır.
   - Yazma izni yoksa çıkış 2 ve eksik kuralı yazar → kullanıcının onayladığı dar dizinse `--izin-ekle`.
   - Komut izni (`--komut "python3 -m pytest"`) yalnız gerekiyorsa ve dar önekle; yoksa terminal kapalıdır.
     Ajan izinsiz komut denerse görev boşa gider — görev metnine "komut çalıştırma" yaz.
   - Aynı etiket çalışırken ikinci başlatma reddedilir (çıkış 3).
3. **Bitişi bekle**: Bash `run_in_background: true` ile `baton bekle ETIKET [ETIKET...]` → bitince bildirim gelir.
   Ön planda uzun bekleme YOK. Ara durum: `baton durum`, canlı akış `baton izle ETIKET`.
4. **Denetle**: `baton rapor ETIKET` → diff'i oku → testleri/derlemeyi KENDİN çalıştır.
   Raporu kanıt sayma; kanıt = test/derleme çıktısı.
5. **Düzeltme**: `baton devam ETIKET -m "Şu testler kalıyor: <özet>. Testleri gevşetme; kök nedeni düzelt."`, ardından tekrar `baton bekle ETIKET` (arka planda) —
   ya da otomatik döngü: `baton dogrula ETIKET --test "<komut>" --tur 2` (`--tur N`: en fazla N düzeltme turu, test en fazla N+1 kez çalışır; varsayılan 3).
6. **İptal / temizlik**: `baton iptal ETIKET` (yalnız çalışan görevde çalışır; değilse çıkış 1), `baton temizle --gun 7`.

## Token
- Claude limitini koru: kod yazımını Gemini'ye ver (Claude kotasından düşmez); Claude yalnız planlar ve doğrular.
- `ajan-yonetici` Sonnet'te kalır; Opus'u yalnız kullanıcı açıkça isterse seç.
- Claude tarafında `baton rapor` kullan; `baton izle` ve tam `yanit.md` okuma bağlamı şişirir.
- Her `devam` turu tüm konuşmayı yeniden işler; ikinci tur çoğu zaman ilkinden pahalıdır.
  `dogrula --tur` değerini düşük tut. Konuşma uzadıysa teşhisi yazıp yeni görev aç.
- Görev metnini kısa ve kesin tut; ajanın okuması gereken dosyaları adıyla ver.

## Paralellik
Farklı dosyalara dokunan görevler aynı anda çalışabilir. Aynı dosyayı düzenleyen iki görevi paralel verme.

## Kurallar
- Kullanıcının kendi açtığı etkileşimli `agy` oturumuna dokunma.
- `--dangerously-skip-permissions` kullanma; izinler dar dizin/önek kuralıyla.
- Ajanın yazdığı testlerde eşik gevşetilmiş mi kontrol et.
