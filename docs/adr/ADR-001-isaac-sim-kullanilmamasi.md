<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ADR-001 — Isaac Sim / Isaac ROS kullanılmayacak

**Durum:** Kabul edildi · **Tarih:** 2026-09-15 · **Kaynak:** NEML_SPEC.md §2

## Bağlam

Robot simülasyonu için iki gerçekçi seçenek vardı: NVIDIA Isaac Sim (+ Isaac
ROS) ve Gazebo Harmonic + `ros_gz`. Isaac Sim fotogerçekçi render, hazır
sentetik veri üretimi ve GPU hızlandırmalı fizik sunar. NEML'in laboratuvar
istasyonunda kullanılabilir GPU belleği **3 GB**'dır (§4.1) ve bu bellek
zaten vLLM tarafından kullanılmaktadır (§4.5).

## Karar

Isaac Sim ve Isaac ROS **kullanılmayacaktır**. Tek simülasyon ortamı Gazebo
Harmonic'tir; ROS 2 köprüsü `ros_gz`, fizik motoru DART'tır (§11.1).

## Gerekçe

- Isaac Sim tek başına 3 GB'ın çok üzerinde VRAM ister; vLLM ile aynı anda
  çalışamaz. Mevcut GPU mutex'i (§4.5) Gazebo `visual` profili için bile
  vLLM'i durdurmak zorundadır — Isaac Sim ile bu durum istisna değil, kural
  olurdu.
- NEML'in evrim döngüsünün %95'i `fast` profilinde, **kamerasız** koşar:
  IMU, enkoder, temas ve LiDAR. Bu sensörler CPU üzerinde yeterlidir;
  fotogerçekçi render'ın ölçülen fitness'a katkısı yoktur.
- Isaac katmanı ikinci bir kurulum hattı, ikinci bir ROS 2 uyumluluk
  matrisi ve ek bir sürüm bağımlılığı getirir. Jazzy + Harmonic resmen
  eşleşen tek hattır (§2).

## Sonuçlar

- Görsel algı skill'leri Gazebo'nun kendi render'ı ile, `visual` profilinde
  ve vLLM durdurularak eğitilir (§4.5). Bu ~40 s'lik yeniden başlatma
  maliyeti planlamaya dahildir.
- Sentetik veri kalitesi Isaac'e göre düşüktür; bu, algı skill'lerinin
  kapsamını sınırlar. §19 risk 2'nin tetikte eylemi geçerlidir: gerekirse
  kamera skill'leri Faz 6'ya ertelenir.
- Daha güçlü bir GPU alınırsa bu karar yeniden değerlendirilebilir; o zamana
  kadar tartışmaya kapalıdır (§0.1).
