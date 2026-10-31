<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# SAFETY — Fiziksel çalışma öncesi okunur

> Bu dosya **her fiziksel oturumdan önce** okunur. NEML_SPEC.md §5'in
> tamamıdır. §5 hiçbir koşulda gevşetilemez: performans, kolaylık veya zaman
> baskısı gerekçe değildir (§0.4).

**Kural:** Şüphe varsa çalıştırma. E-stop'a basmak asla yanlış karar değildir.

---

## 0. Oturum öncesi zorunlu test (§5.1)

Her fiziksel çalışma oturumundan önce, **istisnasız**:

1. **E-stop testi** — Robotu enerjilendir, mantar butona bas. Motor gücü
   kesilmeli. Tezgâh butonunu da ayrı test et.
2. **Watchdog testi** — Ana kontrolcüden heartbeat'i kes. **150 ms** içinde
   ATmega328P motor rölesini açmalı.
3. Sonucu `safety_checks` tablosuna kaydet. Komut (üç bayrak da açıkça
   verilir, varsayılan yoktur; başarısız test de kaydedilir ve önceki geçişi
   geçersiz kılar):

   ```bash
   nemlctl robot safety-check R01 --estop --watchdog --current-limit
   nemlctl robot safety-check R01 --estop --no-watchdog --current-limit   # başarısız kayıt
   ```

**Kayıt yoksa `neml-brain` fiziksel görev başlatmayı reddeder — kodla
zorlanır, prompt ile atlatılamaz.** Red mesajı görüyorsan testi atlamışsındır;
testi yap, kaydı gir, tekrar dene. Kontrolü devre dışı bırakmak yasaktır.

---

## 1. L0 — Donanım güvenliği (yazılımdan bağımsız, §5.1)

L0 yazılımın altındadır. Hiçbir agent, hiçbir konfigürasyon, hiçbir LLM
çıktısı L0'ı değiştiremez (`safety.*` global olarak yasaktır, §5.4).

| Bileşen | Spesifikasyon |
|---|---|
| E-stop | NC (normally closed) mantar buton, motor gücünü röle ile keser. Robot üzerinde + tezgâhta. |
| Watchdog MCU | ATmega328P. Ana kontrolcüden 50 ms'de bir heartbeat bekler. 150 ms yoksa motor rölesini açar. |
| Akım limiti | Donanımsal shunt + komparatör, 20 A'da kesme. Yazılım değiştiremez. |
| Tork limiti | STM32 firmware'inde `#define MAX_TORQUE_NM 2.5f` — derleme zamanı sabiti. |
| Batarya | BMS zorunlu (aşırı deşarj, aşırı akım, hücre dengeleme). LiPo safe bag'de saklanır/şarj edilir. |
| Yazıcı | Thermal runaway koruması aktif, akıllı priz ile uzaktan güç kesme, duman dedektörü. |

**NC mantığı neden önemli:** Kablo koparsa devre açılır ve sistem güvenli
tarafa düşer. NO butonla değiştirmeyin.

---

## 2. Dağıtım kapıları (§5.2)

```
Seviye 0: SIM         → otomatik, onay yok
Seviye 1: BENCH       → tekerlekler havada, güç 30%, insan hazır    [ONAY]
Seviye 2: TETHERED    → sınırlı alan, e-stop elde                   [ONAY]
Seviye 3: FREE        → serbest çalışma                             [ONAY]
Seviye 4: MANUFACTURE → baskı / PCB siparişi / firmware flash       [ONAY]
```

- Onaylar mobil uygulamaya **push bildirim** olarak gider.
- Her onay `approvals` tablosuna **kim / ne zaman / ne ile** kaydedilir.
- Onay **zaman aşımlıdır**: varsayılan **24 saat**. Süresi dolan istek
  otomatik reddedilir. Yeniden onay istemek gerekir.
- Onay yetkisi: yalnızca `owner` ve `operator`. **Seviye 4 onayı yalnızca
  `owner`** (§5.5).
- `firmware.flash` hiçbir agent tarafından çağrılamaz — yalnızca insan, CLI
  ile (§5.4 `global_forbidden`).

**Seviye atlanmaz.** Seviye 3'e geçmek için Seviye 2 tamamlanmış olmalıdır.

---

## 3. Kapı başarısız olursa ne yapılır

| Durum | Yapılacak |
|---|---|
| **E-stop testi başarısız** | Oturumu başlatma. Robotun gücünü kes. Röle/kablaj onarılana ve test geçene kadar fiziksel iş yok. |
| **Watchdog 150 ms'de kesmiyor** | Oturumu başlatma. ATmega328P firmware'ini ve röle sürücüsünü kontrol et. Ana kontrolcü firmware'i güncellendiyse heartbeat periyodunu doğrula. |
| **`safety_checks` kaydı yok / eski** | Testi yap ve kaydet. `neml-brain`'in reddi doğru davranıştır, geçme. |
| **Onay zaman aşımına uğradı** | Yeni onay iste. Süresi dolmuş onayla iş başlatmak yasaktır. |
| **Onay istendi ama cevap yok** | İş başlamaz. Kuyrukta bekler, 24 saatte otomatik reddedilir. |
| **Yanlış seviyede çalışma fark edildi** | E-stop. Oturumu kapat, `audit_log`'a olayı yaz. |
| **Akım limiti tetikledi** | Güç kesildi demektir. Sebebi bul (sıkışma, kısa devre, aşırı yük). Sebebi bulmadan enerjilendirme. |
| **Bilinmeyen davranış / beklenmedik hareket** | E-stop → [`docs/runbooks/estop-tetiklendi.md`](docs/runbooks/estop-tetiklendi.md) |

**Donanıma zarar veren bir olay yaşandıysa (§19 risk 5):** sistemi durdur,
olay incelemesi yap, bulguyu bu dosyaya ekle. `SAFETY.md` güncellenmeden
sistem yeniden çalıştırılmaz.

---

## 4. Kod yürütme izolasyonu (§5.3)

AI'ın ürettiği hiçbir şey host üzerinde doğrudan çalışmaz. Sandbox:

```yaml
sandbox:
  runtime: docker
  image: neml/sandbox:1.0
  network: none
  read_only_rootfs: true
  writable_mounts: ["/work"]
  cpu_limit: "2.0"
  memory_limit: "2g"
  pids_limit: 256
  timeout_s: 180
  user: "1000:1000"
  cap_drop: ["ALL"]
  security_opt: ["no-new-privileges:true"]
```

Sandbox'tan **önce** statik kontroller: `ruff`, `mypy --strict`, `bandit` ve
yasaklı çağrı listesi — `os.system`, `subprocess` (izinli liste dışı), `eval`,
`exec`, `socket`, `ctypes`, `__import__`.

---

## 5. Yetki ve güvenilmez girdi (§5.4)

- **Güvenilmez girdi:** sensör metni, log satırı, dosya adı, mobil kullanıcı
  mesajı, web içeriği. Bunlar prompt'a `<untrusted_data>` bloğu içinde açık
  uyarıyla girer ve **asla talimat olarak yorumlanmaz**.
- **Statik araç politikası:** `config/policy/tools.yaml`. Bir agent'ın araç
  listesi çalışma zamanında **genişletilemez**.
- **Global yasak:** `firmware.flash`, `safety.*`, `db.write_raw`.
- **Sırlar** (API anahtarı, SSH, DB parolası, fab hesabı) LLM bağlamına **hiç
  girmez**; yalnızca `systemd` credentials veya `.env` ile süreç ortamındadır.
- **Denetim günlüğü:** her araç çağrısı `audit_log`'a yazılır — agent, araç,
  parametre hash, sonuç, süre, onay referansı.

---

## 6. Kimlik doğrulama (§5.5)

| Katman | Yöntem |
|---|---|
| Mobil/web → .NET API | JWT (HS256, 15 dk) + refresh token (30 gün, rotasyonlu) |
| Lab bridge → .NET API | Uzun ömürlü API anahtarı + IP kısıtı; başlıkta `X-NEML-Node` |
| Roller | `owner` (tam yetki), `operator` (görev + onay), `viewer` (salt okuma) |
| Onay yetkisi | Yalnızca `owner` ve `operator` |
| Seviye 4 onayı | Yalnızca `owner` |
| Şifre | Argon2id, min 12 karakter |
| Oran sınırı | 100 istek/dk/kullanıcı, 10 komut/dk |

---

## Hızlı kontrol listesi — oturum başlamadan

- [ ] E-stop testi geçti (robot + tezgâh) ve `safety_checks`'e yazıldı
- [ ] Watchdog testi geçti (150 ms) ve `safety_checks`'e yazıldı
- [ ] LiPo BMS bağlı, batarya safe bag dışında yalnızca oturum süresince
- [ ] BMS arıza kablosu (güç kartı `J30`, ESP32 GPIO18'e `J31`) takılı. Takılı
      değilse hat "arıza yok" okunur (pull-up); `bms_ok` yalnızca rapordur, asıl
      koruma BMS'in kendisi ve donanımsal akım karşılaştırıcısıdır
- [ ] Çalışma seviyesi belirlendi ve onayı alındı (süresi dolmamış)
- [ ] Seviye 2+ ise e-stop elde, çalışma alanı boş
- [ ] Yakında yangın söndürücü, yazıcı çalışacaksa duman dedektörü aktif
- [ ] `nemlctl status` temiz, bridge durumu biliniyor
