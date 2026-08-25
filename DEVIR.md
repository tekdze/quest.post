# DEVIR NOTU — quest.post

> Yeni bir sohbete geçerken: **önce bu dosyayı oku.** Kararlar burada, kodda değil.
> Her önemli kararda veya faz bitiminde bu dosya güncellenir.

Son güncelleme: 2026-08-25 (Faz 1 sonu)

---

## 1. Proje özeti

Türkçe indie/oyun haberleri paylaşan, yarı otomatik bir Instagram içerik hattı.

Akış: RSS kaynakları taranır → LLM haberi seçip metne dönüştürür → HTML şablonundan
PNG kart üretilir → Telegram'dan onay istenir → onaylanırsa Instagram'a paylaşılır.

**Hesap:** `@quest.post`
**Dil:** Türkçe, tamamen küçük harf
**Format:** 1080x1350 (4:5) tek kare ve carousel

### Tasarım felsefesi

"AI ürünü" görünmemek birincil kısıt. Bunun teknik karşılığı: **LLM tasarıma hiç
dokunmaz.** Şablon sabit HTML/CSS'tir, LLM sadece metin alanlarını doldurur.
Böylece 300. post 1. postla piksel piksel aynı olur.

---

## 2. Tasarım sistemi

### Fontlar (repoda `fonts/`, OFL lisanslı)
- **Başlık:** Bricolage Grotesque, weight 800, letter-spacing -0.8px, line-height ~1.0
- **Gövde:** Outfit, weight 300–400, line-height 1.45

### Renkler
| Rol | Hex |
|---|---|
| Kırık beyaz (zemin/gradyan) | `#F1EDE3` |
| Mürekkep (başlık) | `#17151A` |
| Gövde metni | `#3B372F` |
| İkincil metin | `#8A8378` |
| Ayraç çizgisi | `#CFC8B8` |

### Tier (nadirlik) sistemi
| Tier | Ad | Renk | Telegram komutu |
|---|---|---|---|
| C | sıradan | `#4A4A4A` | `/c` |
| B | büyülü | `#2A6398` | `/b` |
| A | sıradışı | `#6A4CA6` | `/a` |
| S | mitik | `#D9741F` | `/s` |

Kurallar:
- **C kademesi tek başına yayınlanmaz.** Haftalık derleme carousel'ine biriktirilir.
- Tier'ı LLM belirlemez, kod hesaplar. LLM sadece veri çıkarır (kaç kaynak yazmış,
  oyunun bilinirliği vb.), eşikler Python'da sabittir. LLM'e serbestlik verilirse
  her haberi S yapar.
- Bot kendi önerisini Telegram'da söyler, kullanıcı komutla ezebilir.
- Renk kartta dört yerde görünür: üst şerit (8px), kategori etiketi, madde
  işaretleri, son sayfa logo bloğu.

### Kart anatomisi
- Arka planda oyun görseli, tam kanama (full-bleed)
- Alttan yukarı `#F1EDE3` gradyan; metin bu alanda oturur
- **Gradyanın başlangıç yüzdesi metin bloğunun ölçülen yüksekliğine göre
  hesaplanır.** Sabit bırakılmaz — az metinde fazla beyaz, çok metinde taşma olur.
  Referans: ~30% (kapak, az metin) → ~53% (metin yoğun sayfa)
- Görsel `object-position: 50% 25%` ile üstten hizalanır (karakter yüzleri
  gradyanın üstünde kalsın)
- Metin gölgesi/konturu **yok**. Okunurluk gradyanla sağlanır.
- Carousel'de her sayfa farklı görsel kullanır, ama hepsi aynı oyundan

### Sayfa tipleri
1. **Kapak** — büyük başlık, kicker (`tier · kategori`), alt satırda oyun adı + sayfa sayısı
2. **Metin sayfası** — başlık + paragraf + 2-3 madde
3. **Rakam sayfası** — 2-3 metrik, büyük sayı + açıklama, ayraç çizgileriyle
4. **Son sayfa** — tek soru + iki yumuşak CTA kutusu + künye bloğu
   (logo + `@quest.post` + "haftada üç indie hikayesi")

Son sayfada yasak: "takip et", "beğen", "paylaş", emoji, ok/parmak işaretleri.

---

## 3. İçerik kuralları

### Telif
- Görseller resmi kaynaklardan: IGDB API, Steam basın sayfaları, geliştirici press kit'leri
- Her kartta kaynak kredisi (`görsel: <stüdyo>`)
- **Sızıntı / datamine haberlerinde görsel kullanılmaz** — sadece tipografik kart.
  Sızan materyal paylaşmak DMCA riski. Aynı oyunun resmi key art'ı bile riskli.

### Rakamlar
LLM sayı uydurur. Kural: bir rakam ancak kaynak metninde geçiyorsa karta girer.
Geçmiyorsa **rakam sayfası hiç üretilmez.**

### Görsel seçimi
IGDB görselleri tiplere ayırır (`cover`, `artwork`, `screenshot`, `logo`).
Sayfa tipine göre kod seçer:
- Kapak → `artwork` veya `cover`
- İç sayfalar → `screenshot`
- Son sayfa → `artwork`

Son karar kullanıcıda: bot seçtiği görselleri Telegram'a yollar, kullanıcı
`/1 /3 /5 /2` ile değiştirir veya `/ok` der.

### Metin üslubu — yasak kalıplar
Üretim sonrası filtre bunları yakalar ve yeniden üretim ister:
em-dash, "işte", "peki", "devrim niteliğinde", "oyunun kurallarını değiştiriyor",
soru cümlesiyle başlama, 3'lü madde listesi kalıbı, 2'den fazla hashtag, emoji,
"AI destekli".

Ayrıca her üretimde rastgele bir yazım modu seçilir: gözlem / karşılaştırma /
tarihsel not / sayısal detay / karşı görüş. Sabit açılış kalıbı oluşmasını engeller.

### Kaynak stratejisi
Sadece büyük sitelerden beslenirse herkesin yazdığını yazar. Ayrıştırıcı kaynaklara
ağırlık: itch.io yeni çıkanlar, Steam yeni yayınlananlar, indie geliştirici
devlog'ları, TR stüdyo duyuruları.

**Botun asıl işi yazmak değil, filtrelemek** — 40 haberden 2'sini seçmek.

### İçerik dağılımı
| Tip | Oran | İşlev |
|---|---|---|
| Günlük haber kartı | %50 | Tutma |
| Evergreen carousel | %30 | Büyüme (kaydetme/paylaşma) |
| Liste / karşılaştırma | %15 | Keşfet trafiği |
| Topluluk sorusu | %5 | Yorum sinyali |

Evergreen içeriği bot tek başına üretmez (doğruluk riski). Kullanıcı konu verir
(`/evergreen <konu>`), bot taslak hazırlar.

---

## 4. Mimari

Sunucu yok. Her şey GitHub Actions üzerinde çalışır; kullanıcının bilgisayarı
kapalı olabilir. Telegram bir program değil, posta kutusudur — betik uyandığında
`getUpdates` ile sorar.

### Workflow'lar
| Workflow | Tetik | İş |
|---|---|---|
| `produce.yml` | cron, günde 3 kez | RSS tara → seç → metin üret → kart bas → Telegram'a sor → `pending.json` yaz |
| `respond.yml` | cron, 5 dk | Telegram cevabını oku → paylaş / yeniden üret / iptal → state commit |
| `refresh_token.yml` | cron, aylık | Instagram uzun ömürlü token'ı yenile |
| `urgent.yml` | `workflow_dispatch` | **[İSKELET — sonra doldurulacak]** son dakika viral haber kanalı |

### Son dakika viral haber — ayrılan alan
Tasarımı sonraya bırakıldı, ama iskelet baştan konulacak:
- `workflow_dispatch` ile elle tetiklenebilen `urgent.yml`
- Pipeline'da `priority` bayrağı (normal kuyruğu atlar)
- Telegram'da `/acil <link>` komutu

### Onay akışı
Bot her postta iki seçenek sunar:
- `/otomatik` — API ile kendisi paylaşır
- `/bana` — görselleri Telegram'a atar, kullanıcı indirip uygulamadan
  **Instagram'ın kendi müziğiyle** paylaşır

Not: Instagram Graph API lisanslı müzik / trending audio eklemeyi **desteklemiyor**.
S kademesi postlarda `/bana` tercih edilir.

### Durum yönetimi
Veritabanı yok. Repo içinde JSON, bot kendi commit'ler:
- `state/posted.json` — yayınlanan URL hash'leri (tekrar önleme)
- `state/pending.json` — onay bekleyen post
- `state/tg_offset.json` — Telegram getUpdates offset

### Instagram API notları
- Görsel yüklenemez; **herkese açık URL** gerekir → PNG repoya commit edilir,
  `raw.githubusercontent.com` linki API'ye verilir
- Limit: 24 saatte 100 post (carousel tek sayılır) — kısıt değil
- App Review gerekmez: app development modunda, hesap Instagram Tester olarak eklenir
- Uzun ömürlü token 60 günde ölür → `refresh_token.yml` şart

---

## 5. Dosya yapısı

```
.github/workflows/
  produce.yml
  respond.yml
  refresh_token.yml
  urgent.yml          # iskelet
src/
  feeds.json          # RSS kaynak listesi
  fetch.py            # RSS çek, tekrar filtrele, aday seç
  write.py            # Gemini çağrısı + yasak kalıp filtresi
  tier.py             # tier hesaplama (kod, LLM değil)
  images.py           # IGDB entegrasyonu, görsel seçimi
  render.py           # HTML şablonu → Playwright → PNG
  telegram.py         # soru gönder, cevap oku
  publish.py          # Instagram Graph API
templates/
  card.html           # tek şablon, tüm sayfa tipleri
  card.css
fonts/                # BricolageGrotesque, Outfit (.ttf)
assets/               # logo
state/
```

---

## 6. Secrets (GitHub Actions)

`IG_ACCESS_TOKEN`, `IG_USER_ID`, `TG_BOT_TOKEN`, `TG_CHAT_ID`, `GEMINI_API_KEY`,
`IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET`, `FB_APP_SECRET`

Repo **public** olmalı (Actions dakikası sınırsız).
Settings → Actions → Workflow permissions → **Read and write**
(bot state commit edebilsin diye; atlanırsa sessizce çalışmaz).

---

## 7. Geliştirme sırası

Her faz ayrı ayrı çalıştırılıp doğrulanır, öncekine dönülmez.

| # | Faz | Bağımlılık | Durum |
|---|---|---|---|
| 1 | `feeds.json` + `fetch.py` — RSS çekme, tekrar filtresi | Yok | **✅ 2026-08-25** |
| 2 | `write.py` — Gemini + üslup filtresi | `GEMINI_API_KEY` | sıradaki |
| 3 | `render.py` + `card.html` — PNG üretimi | Fontlar | |
| 4 | `images.py` — IGDB | IGDB anahtarları | |
| 5 | `telegram.py` — onay döngüsü | TG anahtarları | |
| 6 | `publish.py` — Instagram | IG anahtarları | |
| 7 | Workflow YAML'ları + kuru test | Hepsi | |
| 8 | Canlı | — | |

---

## 8. Bilinen sınırlar

- **Otomasyon arzı çözer, dağıtımı çözmez.** Hesap yeni olduğu için ilk aylarda
  erişim düşük olacak. Büyümeyi haber değil evergreen içerik sağlar.
- Actions cron'u yoğunlukta 5–20 dk gecikebilir; haber botu için sorun değil.
- Gemini ücretsiz katmanı günlük ihtiyacın çok üstünde, ama Google istekleri
  ürün geliştirmede kullanabilir.
- ~~Otomasyona geçmeden önce hesapta elle 3-5 post olmalı.~~
  **Kullanıcı bunu bilerek atladı (2026-08-25):** deney amacı, riski kabul edildi.

---

## 9. Faz 1 — kaynak toplama ✅ (2026-08-25)

### Karar değişikliği: arama dili İngilizce

**Kaynaklar İngilizce, çeviriyi `write.py` yapacak.** Türkçe kaynaklar dosyada
duruyor ama `enabled: false`. Sebep tek başına dil tercihi değil, teknik:
kümeleme başlık kelime benzerliğine dayanıyor, TR ve EN başlıklar birbiriyle
eşleşmiyor. Karışık dil havuzunda aynı haber iki ayrı kümeye düşüyor ve
**"kaç kaynak yazmış" sinyali bozuluyor** — o sinyal tier hesabının girdisi.
Tek dile inince sinyal gerçek oldu (ölçüm: 3 → 13 çok kaynaklı küme).

TR kaynakları geri açmak için `feeds.json` içinde `enabled: true` yapmak yeterli.

### `src/feeds.json`

25 kaynak tanımlı, 18'i aktif. Her adres 2026-08-25'te elle yoklandı.
Alan başına anlam:

| Alan | Ne işe yarar |
|---|---|
| `enabled` | false ise hiç çekilmez |
| `weight` | 0.5–1.4. Ayrıştırıcı kaynak yüksek, ana akım düşük |
| `kind` | `news` / `releases` / `devlog` / `community` |
| `bucket` | `news` = post adayı · `discovery` = keşif havuzu, tek başına post olmaz |
| `max_items` | Kaynak başına tavan. itch.io günde yüzlerce kayıt döküyor, tavan olmazsa tek kaynak listeyi yutuyor |
| `topic_filter` | `gaming` = sadece başlıkta oyun anahtar kelimesi geçenler alınır (genel teknoloji/sanat beslemeleri için). Özet metnine **bakılmaz**, neredeyse her özette "game" geçiyor |

**Ölü bulunup alınmayanlar** (tekrar denemeye gerek yok): TIGSource (403),
Warpdoor (RSS kaldırılmış), Tamindir, multiplayer.com.tr (2024'te durdu),
Indie Game Website (2021'de durdu), Steam news feed (bir aylık gecikmeli),
itch.io featured (2021'de dondu), IndieDB'nin `www` adresi (404 — çalışan adres
`rss.indiedb.com`), oyungezer `/feed` (404 — çalışan adres `/rss`).

**Hâlâ eksik:** Steam yeni yayınlananlar (RSS'i yok, Steam store API'si ile ayrı
modül gerekecek), TR stüdyo duyuruları (ortak besleme yok, tek tek eklenmeli).

### `src/fetch.py`

Anahtarsız çalışır: `py -3.12 src/fetch.py --print`

Boru hattı: çek (paralel, kaynak hatası tüm çalışmayı düşürmez) → normalize
(HTML temizle, takip parametrelerini at, başlıktan site adı kuyruğunu sil) →
yaş penceresi (48 sa) → konu filtresi → kaynak başına tavan → tekrar filtresi
(`posted.json`) → kümele → sırala → `state/candidates.json`.

**Kümeleme — en çok uğraşılan yer.** Üç deneme yapıldı:

1. Düz Jaccard (0.45): neredeyse hiç birleştirmedi (312 kayıt → 312 küme).
2. IDF ağırlıklı + "nadir kelime paylaşmak zorunlu": **ters tepti.** Bir haberi
   ne kadar çok kaynak yazarsa anahtar kelimesi o kadar sık hale geliyor, yani
   **büyük haber kendini eliyor.** 4 kaynaklı Gamescom kümesi bu yüzden dağıldı.
3. Çalışan hâl: IDF ağırlıklı oran **+ kanıt kütlesi** (`MIN_SHARED_IDF`)
   **+ özel isim köprüsü** (nadir kelime paylaşılıyorsa oran eşiği düşer, ama
   şart değil). Sonuç: 13-14 doğru küme, elle kontrol edildi.

Bilinen sınır: tek dil şartı (yukarıda), ve bir yazıda iki habere değinen
kaynaklar (RPS'in "Witcher 4 tarihi + Witcher 3 DLC" yazısı gibi) iki kümeyi
birleştirebilir. Zararsız.

Çıktı `state/candidates.json`: `stats`, `feed_health` (hangi kaynak öldü),
`candidates` (post adayları), `discovery` (keşif havuzu).

`feed_health` Faz 5'te Telegram'a bağlanacak: "şu kaynak N gündür sessiz".

### Ayarlanabilir eşikler (`fetch.py` başı)
`CLUSTER_THRESHOLD` 0.30 · `MIN_SHARED_IDF` 3.0 · `BRIDGE_DF` 2 ·
`BRIDGE_THRESHOLD` 0.15 · `SOURCE_COUNT_WEIGHT` 3.0

`rank_score` **tier değildir.** Sadece "hangisine önce bakılsın" sıralaması.
Tier'ı `tier.py` hesaplayacak (Faz 2 sonrası).

---

## 10. Kullanıcı tarafı — anahtar durumu (2026-08-25)

| Ne | Durum |
|---|---|
| Instagram `@quest.post` | Açıldı, bio + pfp hazır, profesyonel hesaba geçirildi |
| GitHub kullanıcı | `tekdze` |
| Telegram bot token | Alındı. **Sohbete yazıldığı için `/revoke` ile yenilenecek**, yeni token doğrudan GitHub Secrets'a girilir |
| Gemini API key | Alınıyor. "Unable to create API key" hatası = Cloud Console'da ToS kabul edilmemiş + proje yok. Elle proje açılınca geçiyor |
| IGDB / Twitch | Yapılmadı |
| Meta developer app | Yapılmadı (Faz 6'ya bırakıldı) |

### Çalışma şekli
- Küçük ve doğrulanabilir adımlar. Bir fazda kod yazılır → çalıştırılıp çıktısı
  gözle kontrol edilir → sonra sonraki faz.
- **Claude yapar:** tüm Python, HTML/CSS şablon, workflow YAML, commit.
- **Kullanıcı yapar:** hesap açma, API anahtarı alma, Secrets girme, Telegram'da
  onay verme, çıktıya bakıp geri bildirim.
- **Anahtarlar asla sohbete yazılmaz, asla koda girmez** — sadece GitHub Secrets.
