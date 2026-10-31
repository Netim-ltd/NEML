<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# NEML Mobil (`neml_mobile`)

NEML laboratuvarının operatör uygulaması. Uzak `neml-api` sunucusuna (§9) bağlanır;
laboratuvara doğrudan bağlanmaz. Kapsam NEML_SPEC.md §10'dur.

**Teknoloji (§10.1):** Flutter 3.47 / Dart 3.13, Riverpod, go_router, dio,
drift (çevrimdışı önbellek), fl_chart, SignalR istemcisi, FCM.
Varsayılan tema Material 3 koyu, varsayılan dil Türkçe (İngilizce ikincil).

## Çalıştırma

```bash
cd mobile
flutter pub get
flutter run                     # bağlı cihaz veya emülatör
flutter analyze && flutter test # CI'nın koştuğu iki komut (§18.2 kapı 3)
flutter run -d chrome           # aynı arayüzü tarayıcıda aç
flutter build web --release     # build/web statik web paketi
```

Yerelleştirme dosyaları (`lib/l10n/app_tr.arb`, `app_en.arb`) değiştiğinde
`flutter gen-l10n` ile `app_localizations*.dart` yeniden üretilir.

Web yerleşiminde 960 px ve üzerinde kalıcı bölüm gezinmesi ve geniş filo
panosu bulunur; küçük ekranlarda çekmece kullanılır. Web paketi ayrı bir HTTPS
statik sunucuda barındırılır. Tarayıcıdaki giriş, Flutter uygulamasının ayarlı
uzak `.NET` API adresine gider; API için CORS ve gerçek bir TLS alan adı gerekir.
Kontrol düğümünün yalnızca `127.0.0.1:8080` üzerinde açılan brain API'si bu
operatör API'sinin yerine geçmez. Web push, Firebase web yapılandırması ve
service worker kurulana kadar devre dışıdır.
Web önbelleği için `web/sqlite3.wasm` ile `web/drift_worker.js`, kilitli Drift
2.35.1 sürümünün resmi yayınından alınmıştır. Statik sunucu `.wasm` dosyasını
`application/wasm` içerik türüyle sunmalıdır.

## Sunucu adresi

Varsayılan adres `lib/core/config.dart` içindeki `kDefaultServerUrl`
(örnek adres; kendi sunucunuz için derlerken `--dart-define=NEML_SERVER_URL=https://api.<alan-adınız>`, CI'da `NEML_SERVER_URL` deposu değişkeni).
Operatör bunu **Giriş** ekranından veya **Ayarlar** ekranından değiştirir
(§10.2, ekran 1 ve 13); seçim güvenli depoda (`neml.settings`) saklanır ve
uygulama ilk karede doğru sunucuyla açılır. Derleme zamanı bayrağı yoktur —
adres çalışma zamanında değiştirilebilir olmak zorundadır.

## Ekranlar (§10.2)

`lib/features/` altında, spec'teki sırayla: `login`, `dashboard`,
`robot_detail`, `tasks`, `task_detail`, `brain_console`, `evolution`,
`genome_tree`, `skills`, `approvals`, `manufacturing`, `logs`, `settings`.

## Çevrimdışı davranış (§10.3) — dikkat

Bu kural kolaylık değil güvenlik gerekçesiyle konmuştur ve gevşetilemez:

- Son alınan durum drift ile önbelleğe alınır ve açılışta hemen gösterilir;
  üstte "çevrimdışı — son güncelleme HH:mm" bandı görünür.
- **Çevrimdışıyken yazma işlemleri kuyruğa alınmaz, engellenir.** Robota geç
  ulaşan bir komut tehlikelidir. Kod karşılığı: `core/network/online.dart`
  içindeki `OfflineWriteBlocked`.
- Tek istisna, onay **reddi**dir: güvenli yönde hata olduğu için kuyruğa
  alınır ve bağlantı dönünce gönderilir (`OfflineRejectionQueued`).

Seviye 4 onaylarda (§5.2) uygulama ek metin doğrulaması ister: operatör
"ONAYLIYORUM" yazmadan onay gönderilmez.

## Bildirimler (§10.4)

FCM tetikleyicileri `kPushTriggers` listesindedir; operatör her birini
Ayarlar'dan susturabilir. Onay isteği (seviye 3-4) ve robot `fault`/`estop`
yüksek öncelikli ve seslidir.
