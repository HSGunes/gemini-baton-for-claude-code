---
description: Bir uygulama işini Gemini alt ajanına devret (ajan); Claude doğrular
argument-hint: <yapılacak iş, ilgili dosyalar, doğrulama komutu>
---

Şu işi `gemini-baton:ajan-yonetici` alt ajanına devret:

$ARGUMENTS

Alt ajanı çağırmadan önce gerekiyorsa kod tabanına kısaca bak ve ona net bir girdi ver: yapılacak iş,
değişecek dosyalar/dizinler, kabul ölçütleri ve doğrulama komutu. Alt ajan döndüğünde sonucunu
kullanıcıya özetle; "BAŞARILI" diyorsa doğrulama çıktısını göster, "İZİN GEREKLİ" diyorsa eksik izin
kuralını kullanıcıya sor.
