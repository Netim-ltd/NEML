<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# vendor/ — dışarıdan kurulan MCP sunucularının konfigürasyonu

Bu dizin **kod içermez** (SPEC §15). Burada yalnızca §6.1'de listelenen, dışarıdan
kurulan MCP sunucularının konfigürasyonu tutulur. Sunucuların kendisi ayrı süreç
olarak, kendi depolarından kurulur ve `scripts/setup/05_mcp_servers.sh` ile
başlatılır.

Kendi yazdığımız dört sunucu (`neml_mcp_sim`, `neml_mcp_fab`, `neml_mcp_genome`,
`neml_mcp_cad`) buraya girmez; onlar §6.2'ye göre bu ağacın içindedir.

## ⚠️ Kurulumdan önce her depo adresi doğrulanır

SPEC §6.1'in uyarısı aynen geçerlidir: `servers.yaml` içindeki depo adresleri
**Mayıs 2026 öncesi** bilgiden gelir. Kurulum yapan kişi her adresi tarayıcıda
açar, deponun yaşadığını ve lisansını doğrular.

- Adres ölmüşse veya depo terk edilmişse: GitHub'da `topic:mcp <araç>`,
  `mcp-server-<araç>`, `<araç>-mcp` biçiminde aranır.
- Uygun bir sunucu bulunamazsa **geri dönüş yolu bellidir:** §6.2'deki
  spesifikasyona göre sunucu kendimiz yazılır (~300-600 satır Python,
  Streamable HTTP). Mimari buna hazırdır; `config/mcp.yaml` dışında hiçbir yer
  değişmez.
- Doğrulama sonucu `servers.yaml` içindeki `verified` alanına tarih ile yazılır.
  `verified: null` olan bir sunucu **kurulmaz**.

## Değişmez kurallar

| Kural | Nerede |
|---|---|
| Transport: Streamable HTTP, stdio değil | §6.2 |
| PostgreSQL MCP **salt okunur** role bağlanır | §6.1 #4 |
| Filesystem MCP yalnızca §6.5'teki iki dizine erişir | §6.5 |
| Fetch MCP yalnızca beyaz listedeki adreslere çıkar | §6.1 #7 |
| GPL/AGPL kod bu ağaca kopyalanmaz; ayrı süreç olarak çağrılır | §1.3 |
| Araç seçimini model yapmaz; çağrıyı LangGraph düğümü yapar | §6.5 |

## Portlar

`config/mcp.yaml` istemci tarafındaki tek kaynaktır; `servers.yaml` yalnızca
kurulum tarafını anlatır. İkisi çakışırsa `config/mcp.yaml` kazanır.

9104 portunu FreeCAD MCP (§6.1 #1) **veya** kendi `neml_mcp_cad` sunucumuz
(§6.2 #13) kullanır — ikisi aynı anda çalışmaz. Hazır sunucu doğrulamayı
geçemezse kendi sunucumuz devreye girer; istemci konfigürasyonu değişmez.

`servers.yaml` içinde `port: null` olan sunucular §6.5 istemci listesinde yer
almaz: opsiyoneldir, benimsenirlerse 9109-9110 aralığından port alır ve
`config/mcp.yaml`'a eklenirler.

## Sırlar

Bu dizindeki hiçbir dosyaya parola, API anahtarı veya DSN yazılmaz (§5.4).
Değerler `${ENV_DEGISKENI}` olarak referans verilir; gerçek değerler `.env` veya
systemd credentials içindedir.
