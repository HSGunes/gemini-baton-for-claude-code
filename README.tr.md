# gemini-baton-for-claude-code

[![Tests](https://github.com/HSGunes/gemini-baton-for-claude-code/actions/workflows/tests.yml/badge.svg)](https://github.com/HSGunes/gemini-baton-for-claude-code/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Gemini Baton, kodlama işlerini Google'ın `agy` (Antigravity) CLI'ı üzerinden bir Gemini alt ajanına veren bir Claude Code eklentisidir. Plan ve son kontrol Claude'da kalır.

Claude görevi ve kabul ölçütlerini yazar. Gemini işi arka planda uygular, Claude da sonucu **senin** testlerinle sınar. Testler kalırsa hata aynı Gemini konuşmasına gönderilir ve orada düzeltilir. Token'ın büyük kısmını harcayan iş Claude kullanımından değil, Gemini kotandan düşer. Bir istem gönderip yanıtı okuyan tek seferlik köprülerden farkı şu: Baton yazma izni olan uzun görevleri yönetir. İzinleri baştan denetler, durumu saklar, konuşmayı sürdürür ve test → düzeltme döngüsünü çalıştırır.

[English README](README.md)

```text
Sen ─▶ Claude Code            planlar, görev dosyasını yazar, senin testlerinle doğrular
         └─▶ baton:ajan-yonetici   isteğe bağlı Sonnet alt ajanı, döngünün tamamını yürütür
               └─▶ baton CLI ─▶ agy ─▶ Gemini   arka planda uygular
```

## Özellikler

- **Arka plan görevleri.** `baslat` hemen döner, `bekle` görev bitene kadar bekler. Bu sırada Claude başka işlere bakabilir.
- **Senin testlerinle doğrulama.** `dogrula --test "<komut>"` testi çalıştırır ve hatayı en fazla `--tur` düzeltme turu boyunca Gemini'ye geri gönderir (varsayılan 3; test en fazla `N + 1` kez çalışır).
- **Bağlamı koruyarak devam.** `devam` aynı Gemini konuşmasını sürdürür (`--conversation <id>`).
- **Dar yazma izni.** Gemini yalnız `--yaz` ile verilen dizinlere yazabilir. Eksik izin kuralı olursa görev, token harcanmadan çıkış 2 ile durur.
- **Varsayılan sandbox.** `--komut` verilmezse terminal kapalıdır (`--sandbox`).
- **Claude bağlamını şişirmez.** `rapor` kısa bir özet basar; isteğe bağlı alt ajan döngünün tamamını ana oturumun dışında tutar.
- **Sıfır bağımlılık.** Tek Python 3.10+ dosyası, yalnız standart kütüphane. 60 test sahte bir `agy` ile çalışır.

## Gereksinimler

- Claude Code (eklenti için)
- `PATH` üzerinde, oturumu açık `agy` (Google Antigravity CLI)
- Python 3.10+
- Linux ya da macOS (CI test paketini ikisinde de Python 3.10–3.13 ile çalıştırıyor). Windows desteklenmiyor.

## Hızlı başlangıç

```bash
claude plugin marketplace add HSGunes/gemini-baton-for-claude-code
claude plugin install baton@gemini-baton
mkdir -p ~/.local/bin
ln -sfn "$(ls -d ~/.claude/plugins/cache/gemini-baton/baton/* | sort -V | tail -1)/bin/baton" ~/.local/bin/baton
baton --help
```

`ln` adımı gerekli, çünkü Claude Code eklentinin `bin/` dizinini `PATH`'e eklemez. `~/.local/bin` `PATH`'te değilse ekleyin.

Sonra Gemini'nin projene yazmasına izin ver; bu her proje için bir kez yapılır ve önce agy'nin `settings.json` dosyasının yedeği alınır:

```bash
cd projen
baton izin kontrol --yaz "$PWD" --izin-ekle
```

Bu kural yoksa alt ajan `İZİN GEREKLİ` ile durur ve eklenmesi gereken kuralı tam olarak yazar; izni hiçbir zaman kendi başına eklemez. Claude Code'u yeniden başlattıktan sonra şunu yaz:

```text
/baton:devret src/parser.py'ye girdi doğrulaması ekle; boş metin ValueError fırlatsın. Doğrulama: python3 -m pytest tests/test_parser.py
```

Claude işi `baton:ajan-yonetici` alt ajanına verir. Alt ajan görev dosyasını yazar, Gemini'yi başlatır, bekler, testi kendisi çalıştırır ve `BAŞARILI`, `BAŞARISIZ` ya da `İZİN GEREKLİ` sonucunu değişen dosyalar ve test çıktısıyla birlikte döndürür.

## Kullanım

### Claude Code içinden

| Ne yaparsın | Ne olur |
|---|---|
| `/baton:devret <iş>` | Alt ajan döngünün tamamını yürütür ve kısa, kanıtlı bir sonuç döndürür. |
| Claude'a "bunu Gemini'ye ver" dersin | `ajan` skill'i devreye girer ve Claude döngüyü kendisi yürütür. |
| Birbirinden bağımsız birkaç iş verirsin | Claude bunları paralel başlatır. Skill, aynı dosyalara dokunan işleri aynı anda çalıştırmamasını söyler. |

### Terminalden

```bash
# 1. Görevi arka planda başlat (Gemini yalnız ./src içine yazabilir)
baton baslat parser-fix -m "parse() boş girdide ValueError fırlatsın" --yaz ./src

# 2. Bitmesini bekle
baton bekle parser-fix

# 3. Kısa raporu oku: özet, değişen dosyalar, açık konular
baton rapor parser-fix

# 4a. Testler kaldıysa aynı konuşmada devam et
baton devam parser-fix -m "tests/test_parser.py::test_empty hâlâ KeyError veriyor. Kök nedeni düzelt, testleri gevşetme." --bekle

# 4b. Ya da test → düzeltme döngüsünü baton'a bırak
baton dogrula parser-fix --test "python3 -m pytest tests/test_parser.py" --tur 2
```

Uzun işlerde bağlamı Markdown dosyalarına yazıp `-g` ile ver (`-g A -g B` ve `-g A B` ikisi de birden çok dosya kabul eder; örnek: [examples/GOREV_ORNEK.md](examples/GOREV_ORNEK.md)).

## Komutlar

| Komut | Seçenekler |
|---|---|
| `baslat <etiket>` | `-g DOSYA...` ya da `-m METİN`, `--model`, `--effort`, `--yaz DİZİN`, `--oku DİZİN`, `--komut ÖNEK`, `--sure 30m`, `--sandbox`, `--izin-ekle`, `--bekle` |
| `bekle [<etiket>...]` | `--zaman-asimi SANİYE` |
| `durum [<etiket>]` | `--json` |
| `rapor <etiket>` | `--ham` (ham yanıt) |
| `devam <etiket>` | `-m METİN` (zorunlu), `--bekle` |
| `dogrula <etiket>` | `--test KOMUT`, `--tur N` (en fazla N düzeltme turu, varsayılan 3), `--cwd DİZİN`, `--zaman-asimi SANİYE` |
| `izle <etiket>` | canlı olay akışı |
| `iptal <etiket>` | çalışan görevi durdurur: SIGTERM, 5 sn sonra SIGKILL (çalışmıyorsa çıkış 1) |
| `temizle` | `--gun GÜN` (varsayılan 7) |
| `izin kontrol` | `--yaz`, `--komut`, `--izin-ekle` |
| `modeller` (`models`) | `--yenile` (`--refresh`), `--json` |

Görev etiketleri (`<etiket>`) yalnız `[A-Za-z0-9._-]` karakterlerinden oluşabilir ve 1–64 karakter uzunluğunda olmalıdır.

Model takma adları `agy models` kataloğundan dinamik olarak türetilir (`<aile>`, `<aile>-high`, `<aile>-orta`, `<aile>-low`; tam model kimliği de verilebilir). Varsayılan model otomatik belirlenir: hesapta mevcut olan ilk aile tercih sırasıyla (`neon` → `hydrogen` → `argon` → `flash`) seçilir; `AJAN_MODEL` ya da `--model` ile değiştirilebilir. Kullanılabilir aileleri ve takma adları görmek için `baton modeller` çalıştırılır. Katalog 24 saat önbelleklenir; yenilemede yeni bir Gemini ailesi görülürse stderr'e tek satır bilgi yazılır.

## Yapılandırma

| Değişken | Varsayılan | Amaç |
|---|---|---|
| `AJAN_DIL` | `tr` | `--help`, ileti ve istem dili: `tr` ya da `en` |
| `AJAN_AGY` | `agy` | `agy` ikilisinin yolu |
| `AJAN_DIZIN` | `$XDG_STATE_HOME/ajan` ya da `~/.local/state/ajan` | Görev durum dizini |
| `AJAN_AYAR` | `~/.gemini/antigravity-cli/settings.json` | agy izin dosyası |
| `AJAN_MODEL` | otomatik | Varsayılan model takma adı ya da tam kimlik (`--model` bunu ezer) |

## İzinler

`agy` izin listesini `settings.json` dosyasından okur:

```json
{ "permissions": { "allow": ["write_file(/mutlak/yol/proje/src)", "command(python3 -m pytest)"] } }
```

`baton baslat`, her `--yaz` dizininin ve `--komut` önekinin bu listede olup olmadığını denetler. Eksik kural varsa çıkış 2 ile durur ve eklenmesi gereken kuralları yazar. `--izin-ekle` önce zaman damgalı bir yedek alır, sonra eksik kuralları ekler. `settings.json` geçerli JSON değilse dosyaya dokunulmaz ve komut hata verir.

## Token'ı düşük tutmak

- Her `devam` turu tüm Gemini konuşmasını yeniden okur; ikinci tur çoğu zaman ilkinden pahalıdır. `dogrula --tur` değerini düşük tut. Konuşma uzadıysa teşhisi yazıp yeni görev aç.
- Mekanik işlerde `--model flash-orta` kullan; daha az thinking token harcar.
- Claude tarafında `izle` ya da `rapor --ham` yerine `rapor` kullan.
- `agy`, global olarak etkin MCP sunucularını ve tüm araç setini her göreve yükler; bunu hesaba kat.

## Sınırlamalar

- Yerelde kurulu ve oturumu açık bir `agy` gerekir. Görevler aynı makinede çalışır; uzak makinede çalıştırma desteği yok.
- Komut adları Türkçedir (`start`, `wait`, `report` gibi İngilizce takma adlar da çalışır). `AJAN_DIL=en` ile `--help`, durum iletileri ve görev istemleri İngilizce olur; `agy` çıktısı ve görev içeriği olduğu gibi kalır.
- `durum` çıktısındaki token sayısı girdi ve çıktıyı kapsar; cache okumaları görünmez.
- Anthropic ya da Google ile bağlantılı değildir.

## Geliştirme

```bash
git clone https://github.com/HSGunes/gemini-baton-for-claude-code.git
cd gemini-baton-for-claude-code
python3 -m pytest                    # sahte agy; gerçek CLI hiç çağrılmaz
claude plugin validate --strict .
ln -sfn "$PWD/bin/baton" ~/.local/bin/baton   # klonu doğrudan kullan
```

Eklenti olmadan da kullanılabilir: `python3 ajan.py --help` kurulum gerektirmez; `pip install .` ise `baton` ve `ajan` komutlarını kaydeder.

Issue ve pull request'ler açık. Davranış değiştiren her değişiklik için bir test ekle.

## Lisans

[MIT](LICENSE)
