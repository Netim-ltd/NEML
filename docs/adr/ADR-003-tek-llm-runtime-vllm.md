<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-003 — Tek LLM runtime: vLLM

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §2, §4.2, §4.7

## Bağlam

Yerel model çalıştırmak için birden fazla seçenek vardır: Ollama,
llama.cpp, TGI, vLLM. NEML'in LLM'e tek bir şartı vardır: çıktı
**dilbilgisi ile kısıtlanabilmelidir** (§4.3). Model, şema dışına çıkamamalı;
bu bir doğrulama değil, üretim zamanı garantisi olmalıdır.

## Karar

Tek LLM runtime **vLLM**'dir (Docker, OpenAI uyumlu API, `:8000`).
**Ollama kullanılmayacaktır.** Tek yerleşik model
`Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ`'dur; ikinci model yüklenmez.

## Gerekçe

- vLLM `--guided-decoding-backend xgrammar` ile `guided_choice` ve
  `guided_json` sunar. §4.3'ün "şema dışı çıktı fiziksel olarak imkânsız"
  garantisi bu özelliğe dayanır; bu özellik olmadan mimari çöker.
- OpenAI uyumlu API, `LLMProvider` soyutlamasının (§4.7) hem `VllmProvider`
  hem `RemoteOpenAIProvider` uygulamasını aynı istemci koduyla yazmayı sağlar.
- İki runtime iki kez bellek, iki kez konfigürasyon ve "hangisi çalışıyordu"
  sorusu demektir. 3 GB VRAM'de bu lüks yoktur.
- Apache-2.0 lisanslıdır; §1.3 kapsamında çıktı mülkiyetine etkisi yoktur.

## Sonuçlar

- vLLM konteyneri (`neml-vllm`) GPU mutex'inin (§4.5) yönettiği kaynaktır;
  `visual` sim profilinde **durdurulur**, koşu bitince başlatılır.
- Model değişimi `config/llm.yaml` ve compose komut satırından yapılır;
  kod değişmez.
- Uzak model yolu (`RemoteOpenAIProvider`) kapalıdır ama **test edilir**.
  Kapalı olması eksiklik değil, bilinçli karardır (§4.7).
