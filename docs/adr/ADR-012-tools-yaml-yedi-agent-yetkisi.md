<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-012 — tools.yaml: eksik yedi agent en dar yetkiyle tanımlandı

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **Kaynak:** NEML_SPEC.md §5.4, §8.2, §16 Faz 5-6
**Tür:** Spesifikasyon değişikliği — sahip kararı

## Bağlam

§8.2 on bir agent tanımlar. §5.4'teki config/policy/tools.yaml ise yalnızca
dördüne (planner, mechanical, manufacturing, electronics) araç verir. Kalan
yedisinin hiç girdisi yoktur.

§5.4'ün "bir agent'ın araç listesi çalışma zamanında genişletilemez" kuralının
en lafzi ve en güvenli okuması deny-by-default'tur: girdisi olmayan agent
hiçbir araç çağıramaz. Uygulama bunu böyle yaptı. Sonuç: evolution, perception
ve swarm agent'ları hiçbir iş yapamıyor, yani Faz 5 ve Faz 6 tıkalı.

## Karar

Yedi agent, işini yapacak en dar yetkiyle tanımlanır:

    orchestrator: {tools: [db.read]}
    coding:       {tools: [db.read, sandbox.run],
                   forbidden: [printer.*, firmware.*]}
    memory:       {tools: [db.read, embed.encode,
                           memory.search, memory.write]}
    reflection:   {tools: [db.read, memory.write]}
    evolution:    {tools: [db.read, sim.read, sim.run,
                           genome.read, skill.read],
                   requires_approval: [genome.activate]}
    perception:   {tools: [db.read, sim.read, sim.capture_camera]}
    swarm:        {tools: [db.read, robot.read],
                   requires_approval: [robot.assign_task]}

§5.4'ün global_forbidden bloğu (firmware.flash, safety.*, db.write_raw)
değişmemiştir ve hepsinin üstünde kalır.

## Gerekçe

- orchestrator yalnızca okur; yönlendirme yapar, iş yapmaz. Yazma yetkisi ona
  gerekmez.
- coding yalnızca sandbox.run alır. §5.3 gereği ürettiği hiçbir şey host
  üzerinde çalışmaz; yazıcı ve firmware açıkça yasaklıdır.
- evolution simülasyon koşabilir ama genome.activate onay kapısındadır: aktif
  genome'u değiştirmek §14.3'ün kabul kriterine ve seviye 4 onayına tabidir.
- swarm görev atayabilir ama robot.assign_task onay gerektirir: fiziksel
  robota iş vermek §5.2 kapılarından geçer.
- perception kamera yakalayabilir; §4.5 gereği bu GPU mutex'ini alır ve vLLM'i
  durdurur, yani zaten pahalı ve sayılı bir işlemdir.

## Sonuçlar

- §5.4'teki tools.yaml bu ADR ile genişlemiştir.
- swarm.py, perception.py ve evolution.py artık yapısal iskelet değil, gerçek
  düğümlerdir.
- requires_approval çözümü tek kuraldır: araç statik olarak verilir, çağrı bir
  onay kimliğine bağlanır. printer.start ve kicad.gerber_export ile aynı
  mekanizma.
- Yetki alt küme testi artık on bir agent için de anlamlıdır; boş yetki
  nedeniyle "trivially true" geçen yedi agent kalmadı.
