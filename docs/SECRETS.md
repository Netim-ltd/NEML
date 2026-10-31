<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Gizli değerler: ne girilecek, nereden alınacak

Dağıtım hattı (`.github/workflows/deploy-control.yml`) GitHub'da **`control-production`**
ortamındaki değerleri okur: `Settings → Environments → control-production`.

## 1. Ortamdaki sekiz değer

| Ad | Tür | Ne gelecek | Nereden alınır |
|---|---|---|---|
| `DOCKERHUB_NAMESPACE` | Variable | Docker Hub kullanıcı/organizasyon adı, küçük harf | hub.docker.com giriş adın |
| `DOCKERHUB_USERNAME` | Secret | Aynı hesabın kullanıcı adı | hub.docker.com |
| `DOCKERHUB_TOKEN` | Secret | Erişim belirteci (Read & Write) | hub.docker.com → Account Settings → Personal access tokens |
| `DEPLOY_HOST` | Secret | Sunucunun adresi (IP ya da alan adı) | Sunucu sağlayıcın |
| `DEPLOY_USER` | Secret | Sunucuda dağıtım kullanıcısı | Sunucuda senin oluşturduğun kullanıcı |
| `DEPLOY_SSH_KEY` | Secret | O kullanıcının **özel** SSH anahtarı (`-----BEGIN ...` ile tamamı) | `ssh-keygen -t ed25519 -f neml-deploy`; genel anahtar sunucuya |
| `DEPLOY_KNOWN_HOSTS` | Secret | Sunucunun parmak izi satırı | `ssh-keyscan -t ed25519 SUNUCU` çıktısı |
| `NEML_API_ENV` | Secret | **Aşağıdaki 2. tablo**, dosyanın tamamı | `generate_secrets.py` üretir |
| `NEML_BRAIN_ENV` | Secret | **Aşağıdaki 3. tablo**, dosyanın tamamı | `generate_secrets.py` üretir |

İlk altı değer girilmiş görünüyor. Son iki değer iş içinde boş geldi; yeniden girin.

### Son iki değeri üretmek

Rastgele değerleri elle uydurma, betik üretsin. Dosyalar repo dışına, yalnızca senin
okuyabileceğin şekilde yazılır; ekrana secret basılmaz.

```bash
python scripts/setup/generate_secrets.py --out ~/neml-secrets \
  --owner-email SENIN@MAILIN --namespace DOCKERHUB_ADIN --tenant firmakisaadi \
  --db-host VERITABANI_ADRESI --api-db-password '...' --brain-db-password '...' \
  --llm-url https://GPU_ADRESI/v1 --embed-url https://EMBED_ADRESI \
  --mcp-base https://LAB_ADRESI
```

Eksik bıraktığın her değer `replace-me` olarak kalır ve betik "still to fill" listesinde
yazar. Sonra kontrol:

```bash
python scripts/setup/check_control_env.py ~/neml-secrets/NEML_BRAIN_ENV.txt
python scripts/setup/check_api_env.py ~/neml-secrets/NEML_API_ENV.txt ~/neml-secrets/NEML_BRAIN_ENV.txt
```

İkisi de geçerse dosyaların **içeriğini** GitHub'a ilgili secret'a yapıştır.

## 2. `NEML_API_ENV` (bulut API'si)

| Anahtar | Ne | Kaynak |
|---|---|---|
| `ASPNETCORE_ENVIRONMENT` | `Production` | sabit |
| `ConnectionStrings__Default` | `neml_cloud` veritabanı bağlantısı, `SSL Mode=VerifyFull` şart | Dış PostgreSQL: adres, `neml` kullanıcısı ve şifresi |
| `Jwt__Key` | ≥ 32 rastgele karakter | betik üretir |
| `Bridge__ApiKey` | ≥ 32 karakter, **`NEML_API_KEY` ile aynı** | betik üretir, ikisine de yazar |
| `Bridge__NodeIds__0` | Lab düğüm adı, `neml-control-01` | sabit |
| `NEML_OWNER_EMAIL` | Sahip hesabının e-postası, uygulamaya bununla girersin | senin e-postan |
| `NEML_OWNER_PASSWORD` | ≥ 12 karakter, uygulama giriş şifresi | betik üretir, dosyadan oku |

## 3. `NEML_BRAIN_ENV` (lab beyni)

| Anahtar | Ne | Kaynak |
|---|---|---|
| `NEML_DOCKERHUB_NAMESPACE` | Docker Hub adın | `DOCKERHUB_NAMESPACE` ile aynı |
| `NEML_DB_URL` | `postgresql+asyncpg://neml:ŞİFRE@HOST:5432/neml?sslmode=verify-full` | Dış PostgreSQL |
| `NEML_VLLM_URL` | `https://.../v1`, https şart, loopback olmaz | GPU makinen |
| `NEML_EMBED_URL` | `https://...` | Embedding servisi |
| `NEML_MODEL` | `Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ` | sabit |
| `NEML_CLOUD_WS` | `wss://api.neml.example.com/bridge/ws` | sabit |
| `NEML_NODE_ID` | `neml-control-01`, API'deki `Bridge__NodeIds__0` ile aynı | sabit |
| `NEML_API_KEY` | `Bridge__ApiKey` ile aynı | betik üretir |
| `NEML_OWNERS` | **`NEML_OWNER_EMAIL` ile aynı e-posta** (aşağıya bak) | senin e-postan |
| `NEML_TENANT_ID` | Firma kısa adı: küçük harf, rakam, `-`/`_` | sen seç, örn. `netim` |
| `NEML_TRAINING_EXPORT_KEY` | ≥ 32 rastgele karakter | betik üretir |
| `NEML_MODEL_SIGNING_SEED` | 64 hex karakter (32 bayt) | betik üretir |
| `NEML_MCP_URL_*` (9 adet) | `https://LAB/<ad>/mcp` | lab geçidin; `--mcp-base` ile hepsi dolar |
| `NEML_OPERATION_ROUTES` | `{}` | onaylı adaptör olana kadar boş kalır |

### `NEML_OWNERS` nedir?

Seviye 4 (fiziksel değişiklik) onayını yalnızca sahip verebilir. Uygulamada onay verdiğinde
sistem kararı **giriş e-postanla** damgalar; lab, o e-posta `NEML_OWNERS` listesindeyse kabul
eder. Yani değer, `NEML_OWNER_EMAIL` ile **aynı e-postadır**. İki kişi sahipse virgülle ayır:
`ben@firma.com,ortak@firma.com`. Boş bırakırsan seviye 4 onayı kimse tarafından verilemez
(güvenli taraf).

## 4. Lab makinesi `.env`

`.env.example` → `.env` kopyala. `CHANGEME` yazan her değer için:

| Anahtar | Ne gelecek |
|---|---|
| `NEML_DB_URL`, `POSTGRES_PASSWORD`, `POSTGRES_RO_PASSWORD` | Lab PostgreSQL şifreleri; sen belirle (≥ 20 karakter) |
| `HF_TOKEN` | huggingface.co → Settings → Access Tokens (Read) |
| `NEML_API_KEY` | Bulut tarafındaki `Bridge__ApiKey` ile aynı |
| `PRUSALINK_API_KEY` | Yazıcı arayüzü → Settings → API key |
| `Jwt__Key`, `ConnectionStrings__Default` | Yalnızca bulut API'sini bu makinede de çalıştıracaksan |
| `NEML_MODEL_SIGNING_SEED` | 64 hex; `python -c "import secrets;print(secrets.token_hex(32))"` |
| `NEML_OWNERS` | Sahip e-postası |

`.env` git'e girmez, sunucuya yalnızca korumalı kanaldan taşınır.
