<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Hiyerarşik robot platformu — uygulama kararı

Bu belge NEML_SPEC.md üzerine eklenen genişlemeyi tanımlar. Mevcut fiziksel güvenlik
kapıları geçerlidir. Öğrenen model, güvenlik zarfını veya acil durdurmayı değiştiremez.

## Uygulama durumu

`brain/neml_brain/platform/` komuta ağacı, kiracı/domain kapsamı, örnek ev/tarla
eklentileri, küçük CPU politikası, Ed25519 model imzası, epizot seçimi, gece
penceresi, simülasyon/canary/geri alma kararları, yetenek boşluğu ve 50 USD BOM
kapısını içerir. `0004_platform.py` migrasyonu yeni kayıtlar için PostgreSQL
RLS, olay ve outbox tablolarını kurar. Bulut onay kararı artık labda işlenir;
model bileti ve robot teyidi ayrı Ed25519 anahtarlarıyla doğrulanır. FreeCAD,
KiCad ve Blender MCP adaptörleri ile tasarım iş akışı eklenmiştir.

**Henüz tamamlanmayan üretim entegrasyonları:** Mevcut .NET/web/mobil ve eski
NEML tabloları paylaşımlı çoklu kiracı yetkileriyle dönüştürülmedi. Canlı
Gazebo'nun tam aday politikayı çalıştırıp model hash'iyle sonuç üretmesi için
`platform/physics.py::GazeboPhysicsRunner` yazıldı (neml-mcp-sim üzerinden); ancak
Gazebo tarafındaki sistem eklentisi (politikayı yükleyip `policy_sha256` döndüren
`neml/*` servisleri) depoda yok. `ScenarioEvaluator` bu kanıt olmadan kabulü
reddeder. Dolayısıyla gece eğitimi otomatik olarak devreye alınmamıştır.
FreeCAD/KiCad/Blender konteynerlerinin gerçek CAD ve medya çalıştırmaları,
robot üstü model ajanının Raspberry Pi/ROS 2 ile birlikte çalışması, uçtan uca
TLS sertifikaları, gerçek veritabanı migrasyonu, fiziksel canary ve rollback
testleri laboratuvar ortamında doğrulanmalıdır. Bu sınırlar tamamlanmadan
paylaşımlı çoklu firmaya dağıtım veya gerçek robot model yayını yapılmaz.

Rancher Desktop hazırlık betiği `scripts/setup/prepare_rancher_desktop.ps1`,
Rancher Manager için çekirdek uygulama chart'ı `deploy/rancher` altındadır.
Chart, PostgreSQL, vLLM, embedding, MCP ve robot donanım servislerini dış
bağımlılık olarak bekler. Kurulum ayrıntıları `docs/RANCHER_INSTALL.md` içindedir.
İlk küçük sunucu kurulumu için Rancher ertelendi; `docs/COMPOSE_CONTROL_PLANE.md`
geçerli Compose yolunu anlatır. Ayrı GPU makinesinde firma/işlem bazlı mini LLM
LoRA aday eğitimi ve hizmeti `docs/NIGHTLY_LORA.md` içinde açıklanır. Bu adaylar
mevcut robot politikası dağıtımından ayrıdır. İmzalı hata/düzeltme raporu,
merkezi kayıt, GPU işçisine aktarım ve görev bazlı öneri API'si bağlanmıştır;
öneri çıktısı robotun eylem grafiğine veya motor denetimine bağlanmaz.

## Çalıştırma hazırlığı

1. `alembic -c brain/alembic.ini upgrade head` ile yeni tabloları kurun.
2. `scripts/platform/generate_signing_key.py` lab anahtarını, robot üzerinde
   `scripts/edge/generate_device_key.py` cihaz anahtarını oluşturur. Özel
   anahtarlar kaynak deposuna konmaz.
3. `scripts/platform/provision.py` ile tenant, domain ve hiyerarşi birimlerini
   kurun; robota yalnızca açık anahtar atanır.
4. `NEML_MODEL_SIGNING_SEED` lab secret manager üzerinden verilir. Fiziksel
   dağıtım yoksa değişken boş kalır ve servis yalnızca diğer işlevlerle açılır.
5. `docker compose --profile edge` model TLS proxy'sini opt-in başlatır;
   varsayılan bağlama adresi 127.0.0.1'dir. Labın belirli LAN IP'si ve güvenilir
   sertifikası ayrıca yapılandırılır. Proxy yalnızca üç imzalı model uç
   noktasını iletir.
6. Robot, `scripts/edge/model_agent.py` ile HTTPS üzerinden bilet arar,
   imzalı dosyayı doğrular, atomik etkinleştirir ve imzalı teyit yollar.

## Bileşenler

```text
Operatör → .NET API/onay → outbound bridge → neml-brain
                                         ├─ komuta ağacı ve olay defteri
                                         ├─ tür eklentileri ve model kayıt defteri
                                         ├─ gece eğitim/dağıtım planlayıcısı
                                         └─ tasarım paketi ve MCP adaptörleri
                                                     ↓
                                           ROS 2 → robot güvenlik zarfı
                                                     ↓
                                           aktüatör / Gazebo
```

Lab tarafı modüler monolittir: tek işlem sınırı ve PostgreSQL işlemleri karar
ile olay kaydını atomik tutar. Robot üstündeki çalışma birimi bağımsızdır.
Cloud yalnızca operatör erişimi ve komut kuyruğudur; lab bağlantıyı dışarı açar.
Komut yazma modeli, durum okuma projeksiyonundan ayrıdır. Olaylar sürümlü,
kiracı/domain kapsamlı ve idempotenttir. PostgreSQL outbox, dış yayın için
kalıcı sınırdır; ayrıca broker kullanımı hacim kanıtlanınca değerlendirilir.

## Sözleşmeler

Her komut `tenant_id`, `domain_id`, `target_id`, `command_id`, `deadline` ve
`parent_epoch` taşır. Komut strateji → domain → takım → robota iner. Epizot,
sağlık ve sonuç olayları ters yönde yükselir. Kiracı ve domain eşleşmeyen emir
reddedilir. Üst katman süresi dolarsa yeni hareket emri yürütülmez; robotun
eklenti tarafından tanımlanan güvenli varsayılanı uygulanır. Bağımsız donanım
watchdog ve e-stop bundan sonra da son söz sahibidir.

Epizot şeması: gözlem, eylem, sonuç, ödül, hata sınıfı, ortam, model sürümü,
zaman ve veri kalitesi. Ham ev içi görüntüler varsayılan olarak eğitim
deposuna girmez. Saklama ve erişim politikaları kiracı/domain bazlıdır.

## Gece hattı ve model yayınlama

Europe/Istanbul saat diliminde 23:59–04:59 çalışır. Toplama → kalite/dedupe →
replay ile tür başına eğitim → sabit regresyon ve geçmiş hata senaryoları →
Gazebo doğrulaması → imzalı aday → insan onayı → canary → filo akışı vardır.
04:59'da bitmeyen iş iptal edilir; etkin model değişmez. Canary metrik düşüşü
geri almayı tetikler. Gerçek robota canary ve filo geçişleri için ayrı insan
onayı gerekir. Modelin aktüatöre gönderdiği her çıktı sabit güvenlik zarfından
geçer. Model kartı veri aralığını, metrikleri, türü, imzayı ve rollback
referansını taşır.

## Tasarım ve maliyet

İlk gerçek prototipin parça maliyeti **50 USD altında** olmalıdır. Kargo,
vergi ve yazıcı sarf malzemesi ayrı raporlanır; belirsiz maliyet onay için
uygun değildir. Başarı ve gerçek ölçüm arttıkça model/robot bütçesi ancak
konfigürasyondaki aşamalı kapılardan geçerek yükselir. Bu ekonomik varsayım
prototip denemesi içindir; donanım güvenlik doğrulaması maliyet adına atlanmaz.
Sistem sipariş veya baskı başlatmaz. Tasarım paketi ve satın alma isteği
yalnızca izinli adrese, insan onayı sonrası iletilir.

FreeCAD kaynak CAD'dir. Blender yalnızca FreeCAD'den dışa aktarılan geometriyle
tanıtım fotoğrafı, video ve montaj animasyonu üretir; parametrik kaynak veya
imalat doğrulayıcısı değildir. KiCad şematik/PCB/BOM ve ERC/DRC sahibidir.
Bu karar NEML_SPEC.md §2'deki Blender yasağını bu sınırlı amaçla değiştirir;
spesifikasyonun sonraki revizyonunda karar tablosu da güncellenmelidir.

## Fazlar

1. Hiyerarşi, kapsamlı komut/olay sözleşmeleri, bağlantı kaybı davranışı.
2. Ev ve tarla tür eklentileri, model kayıt defteri, imza ve geri dönüş.
3. Gece penceresi, epizot seçimi, aday değerlendirme, canary/rollback.
4. Yetenek boşluğu, maliyetli tasarım paketi, onay ve satın alma isteği.
5. FreeCAD/KiCad/Blender/e-posta adaptörleri ve simülasyon senaryoları.

## Açık entegrasyon sınırı

Python çekirdeğindeki sözleşmeler gerçek ROS 2 ve cloud API'ye adaptörle
bağlanır. Çoklu kiracı izolasyonu için mevcut tek kiracılı SQL tablolarının
bir bölümüne `tenant_id` eklemek tek başına yeterli değildir: tüm sorgular,
bridge mesajları, API yetkileri, dosya yolları ve cache anahtarları birlikte
taşınmalıdır. Bu geçiş tamamlanmadan birden fazla firma aynı kurulumda
barındırılmamalıdır.
