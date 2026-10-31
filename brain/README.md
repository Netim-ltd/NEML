<!--
Copyright (c) 2026 Mustafa Gulsoy.
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# neml-brain

Laboratuvar beyni: FastAPI + LangGraph orkestrasyonu, PostgreSQL checkpoint'i,
APScheduler görev kuyruğu. Sözleşme: `NEML_SPEC.md` §8.

## Gereksinimler

- Python 3.12 (paket `>=3.12,<3.13` ile sınırlıdır)
- [uv](https://docs.astral.sh/uv/) 0.10+
- Çalışan PostgreSQL 16 + pgvector (`docker compose up -d postgres`)

## Kurulum

Depo kökünden:

```bash
cd brain
uv sync --extra dev        # sanal ortamı .venv altında kurar
```

## Ortam değişkenleri

`.env.example` (§17.3) dosyasındaki değerler okunur. En az şunlar gereklidir:

| Değişken | Açıklama |
|---|---|
| `NEML_DB_URL` | `postgresql+asyncpg://neml:...@localhost:5432/neml_local` |
| `NEML_VLLM_URL` | vLLM OpenAI uyumlu uç noktası |
| `NEML_EMBED_URL` | Gömme (embedding) servisi |
| `NEML_WORK_DIR` | Geçici çalışma dizini |
| `NEML_ARTIFACT_DIR` | Üretilen çıktıların dizini |

## Veritabanı migrasyonları

Alembic yapılandırması depo kökünden çalışacak biçimde ayarlıdır; veritabanı
adresi `alembic.ini` içinde **yazılı değildir**, `NEML_DB_URL` ortam
değişkeninden okunur.

```bash
alembic -c brain/alembic.ini upgrade head
alembic -c brain/alembic.ini revision --autogenerate -m "aciklama"
```

## Çalıştırma

```bash
cd brain
uv run uvicorn neml_brain.api.app:app --host 0.0.0.0 --port 8080
curl localhost:8080/health
```

Metrikler `:8080/metrics` adresinde Prometheus biçiminde yayınlanır.

Yönetim aracı:

```bash
uv run nemlctl --help
```

## Testler ve statik denetim

```bash
uv run pytest                  # tüm birim testleri, kapsam eşiği %80
uv run pytest -m regression    # simülasyon regresyon paketi (§18.1)
uv run pytest -m "not integration"   # testcontainers gerektirmeyenler
uv run ruff check .
uv run mypy neml_brain
uv run bandit -r neml_brain
```

CI kapıları bloklayıcıdır (§18.2): `ruff` + `mypy --strict` + `bandit` geçmeden
hiçbir değişiklik birleştirilmez.
