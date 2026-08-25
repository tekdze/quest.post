# DEVIR NOTU — quest.post

> Yeni bir sohbete geçerken: **önce bu dosyayı oku.** Kararlar burada, kodda değil.
> Her önemli kararda veya faz bitiminde bu dosya güncellenir.

Son güncelleme: 2026-08-25 (Faz 2 sonu)

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
| 2 | `write.py` — Gemini + üslup filtresi | `GEMINI_API_KEY` | **✅ 2026-08-25** |
| 3 | `render.py` + `card.html` — PNG üretimi | Fontlar | **✅ 2026-08-25** |
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

---

## 11. Faz 3 — kart üretimi ✅ (2026-08-25)

### Dosyalar
| Dosya | Sorumluluk |
|---|---|
| `templates/card.css` | Tasarım sisteminin tamamı. **Sabit.** LLM buraya dokunmaz |
| `templates/card.html` | Tek şablon, dört sayfa tipi. Veriyi `window.CARD_DATA` yerine `renderCard(data)` ile alır, DOM'u kendisi kurar |
| `src/render.py` | Tarayıcıyı sürer: veriyi bas → fontları bekle → gradyanı ölçtür → 1080x1350 PNG |
| `examples/sample_post.json` | Test tarifi. Metinler elle yazıldı (write.py yok henüz) |
| `assets/placeholder.png` | Yer tutucu "oyun görseli". IGDB gelene kadar test için. Chromium'un kendisiyle üretildi, ek kütüphane yok |

Çalıştırma: `py -3.12 src/render.py examples/sample_post.json`

### Fontlar
Variable sürüm kullanılıyor, tek dosya iki iş yapıyor:
`BricolageGrotesque-VariableFont_opsz,wdth,wght.ttf` · `Outfit-VariableFont_wght.ttf`
`@font-face` içinde `format("truetype-variations")` ve `font-weight: 200 800` aralığı şart.

⚠️ `fonts/OFL.txt` **eksik**, eklenmeli — lisans şartı.

### Gradyan hesabı — mekanizma
`card.html` içindeki `fitScrim()` metin bloğunun ekrandaki gerçek yüksekliğini
ölçüp CSS değişkenlerini basıyor. Sabit yüzde yok.

Zincir: `contentTop = 1350 − alt_boşluk − ölçülen_yükseklik` → `solid = contentTop − 38px`
(nefes payı) → `start = solid − 330px` (geçiş uzunluğu).

Ölçülen sonuç (krem alanın alttan kapladığı oran):
kapak %34 · son sayfa %42 · metin sayfası %44 · rakam sayfası %47.

Tasarım notundaki referans "~30% → ~53%" ile tutuyor. **O yüzdeler alttan
sayılıyor** — üstten sanılırsa ters okunur (az metinde çok krem çıkar).
Ayar noktaları: `FADE` (geçiş uzunluğu) ve `BREATH` (metnin üstündeki pay).

Font yüklenmesi metin yüksekliğini değiştirdiği için ölçüm **iki kez** yapılıyor:
bir kez DOM kurulurken, bir kez fontlar ve görsel yüklendikten sonra. Tek ölçümle
gradyan birkaç piksel kayıyordu.

### Türkçe ek kuralı — write.py'ın çözmesi gereken sorun (2026-08-25)

Örnek tarifte `godot'yu` yazılmıştı, doğrusu **`godot'u`**. Yabancı özel isimlere
Türkçe ek eklerken ek **okunuşa** göre seçilir ve bu LLM'in düzenli olarak
yanlış yaptığı bir yer. Kaynak metin İngilizce olduğu için her postta çıkacak.

Çözüm `write.py` içinde iki katmanlı olacak:
1. **Kürasyonlu istisna sözlüğü** — sık geçen özel isimler ve doğru ekli hâlleri
   (godot'u, steam'de, unity'yi, ubisoft'un, valve'ın, xbox'ta, playstation'da).
   LLM'e bırakılmaz, kod dayatır.
2. **Üslup filtresi kontrolü** — sözlükte olmayan bir isme ek geldiyse ve
   apostroftan sonraki ek şüpheliyse yeniden üretim istenir.

Bu, "yasak kalıplar" filtresinin ikinci işi oluyor.

### Uygulanan tasarım kuralları
- Tier rengi tam dört yerde: üst şerit (8px), kicker, madde işaretleri, künye karesi
- `text-transform: lowercase` **CSS'te zorlanıyor** — metin üretiminde bir kaçak
  olursa tasarım bozulmasın diye
- Metin gölgesi/konturu yok, okunurluk sadece gradyanla
- Görsel `object-position: 50% 25%`
- Görsel kredisi (`görsel: <stüdyo>`) her kartta, sağ üstte
- **Sızıntı/datamine modu hazır:** sayfada `image` yoksa kart otomatik
  `card--typographic` oluyor — görsel ve gradyan gizleniyor, düz krem zemin,
  kredi rengi dönüyor. `render.py` o durumda kredi alanını da boş geçiyor

### Bilinmesi gerekenler
- Sayfa tipleri ve bekledikleri alanlar: `cover` (title) · `text` (title,
  paragraph, bullets) · `numbers` (title, metrics[{value,label}]) · `outro`
  (question, ctas[2]). `write.py` bu şemaya uyan JSON üretecek.
- Kapaktaki sayfa sayısı otomatik: tarifte `page_count` yoksa `render.py`
  "4 sayfa" / "tek kare" yazıyor.
- `out/` klasörü **commit edilir** — mimarinin gereği: PNG repoya girmeli ki
  `raw.githubusercontent.com` linki Instagram API'sine verilebilsin.
  `out/sample_post/` sadece test, sonra silinebilir.
- Tier renk/ad tablosu `render.py` içindeki `TIERS`. `tier.py` yazıldığında
  eşikler orada olacak, renk/ad burada kalacak — tek kaynak.

---

## 12. Faz 2 — metin üretimi ⚠️ (2026-08-25)

**Uçtan uca çalışıyor: haber → Türkçe metin → kart.**

### Dosyalar
| Dosya | Sorumluluk |
|---|---|
| `src/write.py` | Gemini çağrısı, istem kurulumu, yeniden üretim döngüsü, render tarifine çevirme |
| `src/style.py` | Üslup filtresi. **LLM çağırmaz, tamamen deterministik** |

Çalıştırma: `py -3.12 src/write.py --index 1 --tier A`
Model listesi: `py -3.12 src/write.py --list-models`

### Anahtar yönetimi
`.env` dosyası proje kökünde, `.gitignore` dışlıyor. `write.py` kendi
`load_env()` fonksiyonuyla okuyor — `python-dotenv` bağımlılığı eklenmedi,
tek işi olan 8 satırlık kod için paket gereksiz.

### Model kararı
`DEFAULT_MODEL = "gemini-3.7-flash"` — **sürüm sabitlendi.**
`gemini-flash-latest` gibi takma ad kullanılmıyor: model sessizce değişirse
üslup da değişir, "300. post 1. postla aynı olur" ilkesi bozulur.

Ölçüm (2026-08-25, `--list-models`): hesapta `generateContent` destekleyen 37
model var. **`gemini-2.5-*` serisi yeni kullanıcılara kapatılmış**
(`NOT_FOUND: no longer available to new users`), yani 3.x zorunlu.

### ⛔ Gemini API bu hesapta kapalı — ARAŞTIRMA KAPANDI (2026-08-25)
`403 PERMISSION_DENIED — Your project has been denied access. Please contact support.`

**Tekrar denemeye gerek yok.** Elenen ihtimaller:

| Denenen | Sonuç |
|---|---|
| Model listesi çekmek (`ListModels`) | ✅ çalışıyor → anahtar geçerli, ağ sorunu yok |
| `gemini-3.7-flash`, `3.5-flash`, `3.1-flash-lite`, `gemma-4-31b-it` | hepsi 403 → model ailesi fark etmiyor |
| `v1beta` / `v1` endpoint | ikisi de 403 |
| Anahtarı header ile / `?key=` ile göndermek | ikisi de 403 |
| Yeni Cloud projesi (`questpost2`) | 403 |
| Gemini API'yi Cloud Console'da enable etmek | zaten enabled'dı, 403 |
| Anahtarı Cloud Console'dan, **servis hesabına bağlı** oluşturmak | 403 |
| Hesap yaşı / kişisel hesap | sorun yok |
| AI Studio **sohbet** arayüzü | ✅ çalışıyor |

Kritik ayrım: **AI Studio sohbeti ile Gemini API iki ayrı kapı.** Sohbetin
çalışması API'nin çalışacağı anlamına gelmiyor, farklı erişim politikaları var.

Not: Google artık Gemini API anahtarlarının bir **servis hesabına bağlı** olmasını
şart koşuyor. Cloud Console'da API kısıtlaması listesinde "Gemini API" ancak
"Authenticate API calls through a service account" işaretlendikten sonra
seçilebilir hale geliyor. Bu yapıldı, engel kalkmadı.

Sonuç: engel proje/hesap seviyesinde bir politika bloğu, kod tarafında
yapılacak bir şey yok. **Sağlayıcı değiştiriliyor.**

### İş bölümü — LLM'in dokunamadığı şeyler
LLM **sadece** şu alanları üretir: `game`, `category` (sabit listeden seçer),
`studio`, `is_leak`, ve sayfa metinleri. Dokunamadıkları: tier, görsel seçimi,
tasarım, sayfa sayısı sınırı, gradyan.

`is_leak` LLM'den geliyor ama sonucu **kod uyguluyor**: true ise `render.py`
görseli ve krediyi tamamen düşürüyor, kart tipografik hale geçiyor. Telif
kuralı LLM'in iyi niyetine bırakılmadı.

### Üslup filtresi — `style.py`
Üç denetim, hepsi deterministik:

1. **Yasak kalıp avı** — em-dash ve eğik tırnak, yasak kelime listesi, emoji,
   büyük harf, 2'den fazla hashtag, "a, b ve c" üçlük kalıbı, soru cümlesiyle
   başlama (son sayfanın sorusu hariç, o tasarımın parçası).
2. **Ek denetimi** — yabancı özel isme yanlış Türkçe ek. Sözlükte olan hatalar
   **yeniden üretim istenmeden otomatik düzeltiliyor** (`autofix_suffixes`):
   yeniden üretim pahalı ve sonucu belirsiz, ek hatası ise mekanik bir düzeltme.
3. **Rakam denetimi** — çıktıdaki her rakam dizisi kaynak metinde geçmek zorunda.
   Geçmiyorsa ihlal. LLM'in en tehlikeli hata tipi bu, çünkü inandırıcı görünüyor.

Doğrulandı (2026-08-25, LLM'siz): uydurma "47 milyon" ve "2019" yakalandı,
`godot'yu` otomatik `godot'u` oldu, em-dash + emoji + "adeta" yakalandı.

İki kusur bulunup düzeltildi:
- `tier` alanı ("A") büyük harf denetimine giriyordu. Düz metin olmayan alanlar
  `NON_PROSE_KEYS` ile ayrıldı.
- Yasak kelime avı Türkçe işaretlere bağımlıydı: LLM "iste" veya "cigir acan"
  yazsa filtre kaçırıyordu. Artık karşılaştırma işaretler sadeleştirilerek
  yapılıyor (`fold()`).

Yeniden üretim döngüsü: en fazla 3 deneme, her denemede önceki ihlal listesi
isteme ekleniyor. 3'te de temizlenmezse hata dönüyor — kirli metin yayına gitmez.

### Sonraki fazda hatırlanacak
- `--tier` şu an elle veriliyor. `tier.py` yazılınca oradan gelecek.
- Görsel `assets/placeholder.png` olarak sabit. `images.py` (Faz 4) devralacak.
- Tam makale metni **çekilmiyor**, kümedeki tüm kaynakların RSS özeti
  birleştirilip veriliyor. Kazıma yapmamak için bilinçli tercih; birden fazla
  özet zaten tek özetten zengin.

### Çözüm: hesap değiştirildi (2026-08-25)
Engel **başka bir Google hesabıyla** aşıldı. Yeni hesapta aynı kod ilk denemede
çalıştı, model listesi de 37'den 50'ye çıktı (daha geniş erişim).

**Öğrenilen:** engel projeye değil **hesaba** bağlıydı. Yeni Cloud projesi açmak,
API'yi enable etmek, anahtarı servis hesabına bağlamak — hiçbiri işe yaramadı.
Bir daha benzer duvara çarpılırsa ilk denenecek şey hesap değiştirmek olmalı,
proje ayarlarıyla uğraşmak değil. Eski/yerleşik bir hesap tercih edilir;
sıfır hesaplar "yeni hesap" filtresine takılabiliyor.

`.env` artık bu ikinci hesabın anahtarını tutuyor. Faturalandırma **bağlı değil**,
yani ücretlendirilme teknik olarak mümkün değil: kota aşılırsa 429 gelir, borç
birikmez.

### Model: `gemini-3.6-flash`
`3.7-flash` ısrarla `503 UNAVAILABLE` (kapasite) döndürdüğü için bir sürüm
geriye alındı. `3.6`, `3.5`, `3-flash-preview` ve `3.1-flash-lite` sorunsuz.

Buna karşı `api_call()` içine yeniden deneme eklendi: 429/500/502/503'te
artan bekleme ile 3 kez tekrar. Cron ile çalışan bir bot tek bir yoğunluk
anında günün postunu düşürmemeli.

### ⚠️ Bulunan ve düzeltilen kritik kusur: işaretsiz Türkçe
İlk gerçek çıktı "gamescom yine ayni reklamlari sunmaya hazirlaniyor" şeklinde,
**Türkçe karakterler olmadan** geldi. Sebep istemin kendisiydi: istem ASCII
Türkçesiyle yazılmıştı, model üslubu birebir kopyaladı.

İki katmanlı düzeltildi:
1. İstemin tamamı düzgün Türkçeyle yeniden yazıldı (kural metinleri, yazım modu
   açıklamaları, şema açıklamaları dahil). **LLM istemin üslubunu taklit ediyor,
   bu yüzden istem kusursuz Türkçe olmak zorunda.**
2. `style.py` içine denetim: 60 karakterden uzun bir metinde ı/ş/ğ/ü/ö/ç
   harflerinden hiç yoksa ihlal sayılıyor.

Ayrıca rakam denetimine sayı kelimeleri eklendi: kaynak İngilizce "two hours"
derken çıktı "2 saat" oluyor, filtre bunu uydurma sanıyordu.

### Doğrulanmış uçtan uca akış
```
py -3.12 src/fetch.py                      # 701 kayit -> 193 kume
py -3.12 src/write.py --index 1 --tier A   # ilk denemede temiz, 4 sayfa
py -3.12 src/render.py state/draft.json    # 4 PNG
```
Çıktı örneği `out/ilk_gercek/`. "karşı görüş" modu gerçekten eleştirel bir
metin üretti, kalıp cümle çıkmadı.

### Sonraki fazda hatırlanacak (güncel)
- `studio` null gelirse kartta görsel kredisi **hiç görünmüyor**. Tasarım kuralı
  "her kartta kredi" diyor. Doğru çözüm: krediyi LLM'den değil `images.py`'den
  (IGDB) almak — görselin sahibini görselle birlikte gelen veri bilir.
- LLM tek harflik yazım hatası yapabiliyor (bir denemede "düşüncelerinizi" yerine
  "dusunceleinizi" çıktı). Filtre bunu yakalamaz. Telegram onayı bu yüzden var.
