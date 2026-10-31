<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-009 — vLLM servisi `docker/compose.yml` içinde, ayrı dosyada değil

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **Kaynak:** NEML_SPEC.md §4.2, §15, §17.4

## Bağlam

§4.2 vLLM servisini `docker/vllm/docker-compose.yml` yolunu **adıyla yazarak**
verir. §15'teki dizin ağacı ise aynı yeri yalnızca `docker/ ... vllm/` olarak,
dosya adı vermeden listeler. §17.4 kurulum adımları ve T-004'ün kabul kriteri
(`docker compose up` — tüm servisler `healthy`) tek bir yığın tanımı varsayar:
postgres, vllm, embed, brain ve MCP sunucuları aynı ağda, `depends_on` ile
sıralanmış olarak ayağa kalkar.

İki dosya tutmak §0.1'in "spec bağlayıcıdır" kuralıyla çelişmez ama iki yerde
aynı bayrak listesi demektir. Bu liste §4.2'de "kesin" olarak işaretlenmiştir;
ikiye bölünmüş bir kopyanın sessizce ayrışması, 3 GB VRAM kısıtının fark
edilmeden ihlal edilmesi anlamına gelir.

## Karar

vLLM servisi **`docker/compose.yml` içinde tek bir `vllm` servisi** olarak
tanımlanır. `docker/vllm/docker-compose.yml` **oluşturulmaz**.
`docker/vllm/` dizini kalır ve içinde yalnızca `README.md` bulunur: parametre
gerekçeleri, yedek model ve T-005 doğrulama adımları oradadır.

§4.2'nin komut satırı `docker/compose.yml` içine **birebir** alınmıştır:
`--model Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ --quantization awq --dtype half
--max-model-len 4096 --gpu-memory-utilization 0.88 --enforce-eager
--max-num-seqs 2 --swap-space 2 --disable-log-requests
--guided-decoding-backend xgrammar`. Konteyner adı `neml-vllm`'dir; §4.5 GPU
mutex'i bu adı durdurur.

## Gerekçe

- Bayrak listesi tek yerdedir; iki kopya ayrışamaz.
- T-004 kabul kriteri tek `docker compose up` ile karşılanır; operatörün iki
  dosyayı `-f` ile birleştirmesi gerekmez.
- `depends_on` ve healthcheck zinciri (brain → vllm `service_started`) ancak
  aynı compose projesi içinde kurulabilir.
- §15'in dizin ağacı yalnızca `vllm/` der; ağaç bozulmamıştır.

## Sonuçlar

- §4.2'de yazılı **yol** ile ağaçtaki yol farklıdır. Bu sapma bilinçlidir ve bu
  kayıtla belgelenmiştir; §0.1 gereği tek taraflı sessiz bir karar değildir.
- §4.2'deki iki değer kasıtlı olarak daraltılmıştır ve bu daraltmalar
  `docker/compose.yml` içinde yorumla işaretlidir: port `127.0.0.1:8000:8000`
  olarak yalnızca localhost'a bağlanır (§17.1), HuggingFace önbelleği
  `${HOME}/.cache/huggingface` bind mount yerine `hf-cache` adlı named volume'dur.
- Bayrakların §4.2 ile aynı kaldığını doğrulamak isteyen, `config/llm.yaml`
  içindeki `providers.vllm` bloğuyla karşılaştırır; iki dosya aynı değerleri
  taşır ve `docker/vllm/README.md` §2 bunu açıkça söyler.
