# DEVIR NOTU — quest.post

> Yeni bir sohbete geçerken: **önce bu dosyayı oku.** Kararlar burada, kodda değil.
> Her önemli kararda veya faz bitiminde bu dosya güncellenir.

Son güncelleme: 2026-08-29 · **Faz 7 bitti.** Bot kendi kendine dönüyor:
menü → seçim → üretim → onay. Tetikleme cron-job.org'da (GitHub cron çalışmadı).
Sırada Faz 6 (Instagram).

---

## 1. Proje özeti

Türkçe indie/oyun haberleri paylaşan, yarı otomatik bir Instagram içerik hattı.

Akış: RSS kaynakları taranır → kademe hesaplanır → LLM haberi Türkçe metne
çevirir → IGDB'den görsel seçilir → HTML şablonundan PNG kart üretilir →
Telegram'dan onay istenir → onaylanırsa paylaşılır.

**Hesap:** `@quest.post` · **Dil:** Türkçe, tamamen küçük harf
**Format:** 1080x1350 tasarım, 1440x1800 çıktı (4:5)

### Tasarım felsefesi
"AI ürünü" görünmemek birincil kısıt. Teknik karşılığı: **LLM tasarıma hiç
dokunmaz.** Şablon sabit HTML/CSS'tir, LLM sadece metin alanlarını doldurur.

### Çalışma şekli
- Küçük ve doğrulanabilir adımlar. Bir fazda kod yazılır → çalıştırılıp
  çıktısı gözle kontrol edilir → sonra sonraki faz.
- **Claude yapar:** tüm Python, HTML/CSS, workflow YAML, commit.
- **Kullanıcı yapar:** hesap açma, API anahtarı alma, Secrets girme,
  Telegram'da onay, çıktıya bakıp geri bildirim.
- **Anahtarlar asla sohbete yazılmaz, asla koda girmez** — sadece `.env`
  (yerel, git dışı) ve GitHub Secrets.

---

## 2. Durum tablosu

| Faz | Ne | Durum |
|---|---|---|
| 1 | `fetch.py` + `feeds.json` — haber toplama | ✅ |
| 2 | `write.py` + `style.py` — metin üretimi ve üslup filtresi | ✅ |
| 3 | `render.py` + `card.html/css` — kart üretimi | ✅ |
| 4 | `images.py` — IGDB görselleri | ✅ |
| 5 | `telegram.py` + `respond.py` — onay döngüsü | ✅ |
| + | `tier.py` + `produce.py` — kademe ve orkestratör | ✅ |
| + | Tasarım turu — kesinleşti 2026-08-27 | ✅ |
| 7 | Workflow'lar — bot kendi kendine çalışıyor | ✅ |
| **6** | **`publish.py` — Instagram paylaşımı (Meta kurulumu)** | **sıradaki** |
| + | `qa.py` — görsel denetim (tasarım oturdu, artık yazılabilir) | bekliyor |

**Bot artık bilgisayar kapalıyken de çalışıyor.** Günde 3 kez menü geliyor,
`/uret <numara>` ile seçiyorsun, kartlar basılıp onaya sunuluyor. Eksik olan
tek şey paylaşımın kendisi: `/ok` desen bile Instagram'a gönderemiyor,
`/bana` ile elle atıyorsun. Faz 6 bunu kapatacak.

### Kurulumu tamamlanmış olanlar
- GitHub Secrets'ta beş anahtar
- Actions → Read and write permissions
- cron-job.org'da iki tetikleyici iş (bkz. bölüm 11)
- Instagram hesabı açık ve profesyonel hesaba geçirilmiş

---

## 3. Boru hattı

```
fetch.py    RSS tara, kümele, tekrarları ele    → state/candidates.json
tier.py     kademe hesapla (kod, LLM değil)
write.py    Gemini → Türkçe metin + style.py    → state/draft.json
images.py   IGDB → görsel seç, indir, kredi     → state/img/
render.py   HTML → Chromium → PNG               → out/<tarih>-<oyun>/
telegram.py kartları yolla, onay iste           → state/pending.json
  kullanıcı  /ok /bana /gorsel /havuz /yeniden /iptal /c /b /a /s
respond.py  kararı uygula
publish.py  [YOK — Faz 6]
```

`produce.py` üretim zincirini, `respond.py` karar uygulamayı sürüyor.
Her aşama **ayrı süreç**: Actions kaydında patlayan aşama tek bakışta
görünsün diye.

---

## 4. Tasarım sistemi — KESİNLEŞTİ (2026-08-27)

Tüm kararlar kullanıcıyla konsept turları yapılarak alındı. Değiştirmeden önce
buradaki gerekçeleri oku.

### Fontlar
`fonts/` altında, OFL lisanslı, variable sürüm:
`BricolageGrotesque-VariableFont_opsz,wdth,wght.ttf` (başlık, weight 800) ·
`Outfit-VariableFont_wght.ttf` (gövde, 300-500)
`@font-face` içinde `format("truetype-variations")` ve ağırlık aralığı şart.

### Renkler
| Rol | Hex |
|---|---|
| Krem (zemin/gradyan) | `#F1EDE3` |
| Mürekkep (başlık, tür kutusu) | `#17151A` |
| Gövde metni | `#3B372F` |
| İkincil metin | `#8A8378` |
| Ayraç çizgisi | `#CFC8B8` |

### Kademe (tier)
| Tier | Ad | Renk |
|---|---|---|
| C | sıradan | `#4A4A4A` |
| B | büyülü | `#2A6398` |
| A | sıradışı | `#6A4CA6` |
| S | mitik | `#D9741F` |

**Kademe rengi kartta üç yerde:** sol dikey şerit (28px, kart boyu), kademe
kutusu, madde işaretleri. Son sayfada dördüncü yer: künye bandı.

⚠️ **Tier renginin üzerine her zaman KREM yazı gelir.** Ölçülen kontrast:
C 7.58 · B 5.38 · A 5.62 · **S 2.78**. S erişilebilirlik sınırının (4.5)
altında. Koyu yazı (5.58) ve turuncuyu koyulaştırma (`#A34D09`, 4.96)
denendi; kullanıcı **kavram bütünlüğü için krem yazıda karar kıldı** —
tek kademenin farklı davranması sistemi bozuyordu. Bilinçli bir ödün.

### Kart anatomisi
- Arka planda oyun görseli, tam kanama
- Alttan yukarı krem gradyan; **başlangıcı sabit değil**, metin bloğunun
  ölçülen yüksekliğine göre `card.html` içindeki `fitScrim()` hesaplıyor.
  Ölçülen krem alan: kapak %47 · metin sayfası %36-40 · son sayfa %50
- Görsel `object-position: 50% 25%` (yüzler gradyanın üstünde kalsın)
- Metin gölgesi/konturu **yok**, okunurluk gradyanla
- Üstte 170px ince karartma: aydınlık gökyüzünde köşe bilgileri okunmuyordu

### Kademe ve tür kutuları (kapakta)
Alt alta iki kutu, **köşe yuvarlatma yok**, şeritten ayrık, genişlik metne göre:
- Üst kutu: kademe adı, tier renginde dolu, Bricolage 800, 27px
- Alt kutu: haber türü, mürekkep dolu, Outfit 500, 23px

Denenip elenenler: tek satır kicker (ızgarada görünmüyordu), geniş üst bant
(görselden 78px alıyor, tarayıcı çubuğu gibi duruyor), yuvarlatılmış köşe
(kullanıcının deyimiyle "AI slop"), şeride bitişik kutu, sabit genişlik
(kısa kelimede boş duruyordu).

### Köşe bilgileri
- **Sağ üst — görsel kredisi:** `@cd projekt red`. Telif kuralı gereği her
  görselli kartta. ("görsel: ..." öneki gereksiz bulundu, kaldırıldı.)
- **Sol üst — sayfa göstergesi:** ilk sayfa `1/5 · kaydır`, sonrakiler
  `2/5`, `3/5`, son `5/5`. Tek sayfalık postta `1/1`.
  İkisi de mutlak konumlu: metin bloğu ölçümünü ve gradyanı bozmasınlar diye.

### Sayfa tipleri
1. **Kapak** — kademe kutusu + tür kutusu + büyük başlık + oyun adı
2. **Metin** — başlık + paragraf + 2-3 madde
3. **Rakam** — 2-3 metrik. Sayı 92px, açıklama 32px koyu, satır aralığı ferah.
   (Önceden sayı 104px / açıklama 27px gri idi; açıklama sayının yanında
   kayboluyordu.)
4. **Son sayfa** — soru + **tek** çağrı kutusu + tier renginde künye bandı
   (`@quest.post` · "oyun dünyasından her gün 3 yeni haber" · sağda kademe
   adı) + takip yönlendirmesi.

### ⚠️ Değişen kural: takip daveti artık serbest
Eski kural "son sayfada takip et / beğen / paylaş yasak" idi.
**Kullanıcı 2026-08-27'de bunu bilerek değiştirdi:** künye bandında
"yenilerini kaçırmamak için takipte kal" sabit metni var. Yasak listesinde
"beğen" ve "paylaş" duruyor; sadece takip daveti serbest.

### Tipografik mod
Görsel eşleşmeyen **her** haber (sızıntı, etkinlik, şirket, sektör) buraya
düşer. Görsel ve gradyan gizlenir, içerik dikeyde ortalanır, başına tier
renginde 104x6px çizgi konur, kapak başlığı 104px'e çıkar. Metni alta
yapıştırmak üstte 800px boşluk bırakıyor ve kart bozuk görünüyordu.

---

## 5. İçerik kuralları

### ⚠️ Görsel adayları (2026-08-29) — haberin konusu oyun olmasa da görsel bulunur
Eskiden `search_name` boşsa kart doğrudan tipografik oluyordu. Ölçülen sonuç:
"yeni xbox konsol ailesi" haberi görselsiz basıldı, oysa haber metninde
**Elder Scrolls 6** tartışılıyordu ve o oyunun IGDB'de görseli vardı.
İstem fazla katıydı — "haber bir oyun hakkında değilse null" kuralı LLM'i
haberdeki oyunları hiç aramamaya itiyordu.

Artık `write.py` iki alan üretiyor: `search_name` (haberin **asıl konusu**)
ve `image_candidates` (metinde **adı geçen**, görseli haberi temsil
edebilecek oyunlar, önem sırasıyla, en fazla 3).

`images.py` seçim sırası:
1. `search_name` tutuyorsa tartışmasız o kullanılır — haberin konusu odur
2. Tutmazsa adaylar **LLM'in sırasıyla** denenir, ilk **yeterli** olan alınır.
   Yeterli = her sayfaya farklı görsel düşecek kadar (`>= sayfa sayısı`)
3. Hiçbiri yeterli değilse en zengin havuzlu aday seçilir — iki görseli olan
   çıkmamış bir oyunu beş sayfaya yaymaktansa
4. Hiçbiri tutmazsa tipografik

Ölçüm: Elder Scrolls VI (2 görsel) atlandı, Halo Infinite (12) seçildi,
üçüncü aday hiç sorgulanmadı. Tek aday yetersiz olsa da kullanılıyor.

⚠️ **Telif kuralı değişmedi:** görsel yine yalnızca IGDB'den, kredi yine
IGDB'nin şirket verisinden (`bethesda game studios`, `343 industries`).
Sızıntı haberinde görsel kullanılmaması kuralı da yerinde.

### ⚠️ Seri yedeği (2026-08-29) — "görsel az" durumu için
Çıkmamış oyunların IGDB'de 1-2 görseli oluyor ve 4-5 sayfaya yayılınca aynı
görsel tekrar ediyordu. Artık `write.py` bir alan daha üretiyor:
`series_fallback` — **aynı serinin** görsel bakımından zengin oyunları.
Konu oyununun havuzu sayfalara yetmiyorsa oradan tamamlanıyor.

Üç kural bunu güvenli tutuyor:

1. **Kapak ASLA yedekten seçilmez.** İlk kart hesabın vitrini; orada haberin
   konusu olmayan bir oyunun görseli okuru yanıltır. `assign_images` içinde
   `page["type"] != "cover"` koşulu.
2. **Kredi sayfa başına.** Bu kritikti: Pokémon TCG Pocket'ın stüdyosu
   `the pokémon company`, ana serininki `game freak`. Tek ortak kredi basmak
   o sayfada **yanlış stüdyoyu** göstermek olurdu — telif kuralının deldiği
   yer tam burası. Kredi artık görselin kendisinde taşınıyor
   (`image_pool` yazıyor), `page["credit"]` olarak taslağa geçiyor,
   `render.py` önce onu basıyor. Ölçüldü: sayfa 1-2 `the pokémon company`,
   sayfa 3-4 `game freak`.
3. **Menüde şeffaf:** `görsel VAR (2 + 2 seriden)` ve hangi oyunlardan
   geldiği yazılı. Kullanıcı bilerek seçiyor.

İstemde "sadece gerçekten AYNI seri olanı yaz, benzer türde başka bir oyun
okuru yanıltır" kuralı var. Menüde de aynı soru soruluyor (`seri` alanı),
ama seri araması **yalnızca havuz yetersizse** yapılıyor — boşuna IGDB
çağrısı yok.

### Telif
- Görseller yalnızca IGDB'den (resmi stüdyo materyali)
- Her görselli kartta kredi, **IGDB'nin şirket verisinden** — LLM tahmininden değil
- **Sızıntı/datamine haberinde görsel kullanılmaz.** `is_leak` LLM'den gelir
  ama sonucu kod uygular: `images.py` görseli ve krediyi düşürür.

### Rakamlar
Çıktıdaki her rakam kaynak metinde geçmek zorunda. `style.py` denetliyor.
Kaynak İngilizce olduğu için sayı kelimeleri de ("two hours" → "2") izinli
kümeye ekleniyor.

### ⚠️ Üslup filtresi görsel bulmayı sabote ediyordu (2026-08-29, düzeltildi)
`style.py` **büyük harfi yasaklıyor** ve `strings_of` taslaktaki her metin
alanını dolaşıyordu. Ama `search_name`, `image_candidates`, `series_fallback`
IGDB'de aranan **tam İngilizce oyun adları** - büyük harf içermek
zorundalar. Denetime girdikleri için her üretimde "büyük harf var" hatası
veriyor, `write.py` üç kez yeniden üretiyor ve LLM sonunda o alanları
**boş bırakmayı öğreniyordu.**

Yani filtre, görsel bulma özelliğini sessizce çalışmaz hale getiriyordu.
Xbox haberinde `search_name: None` gelmesinin sebebi muhtemelen buydu.

Düzeltme: bu alanlar + `studio` `NON_PROSE_KEYS`'e alındı (karta
basılmıyorlar). `studio` yerine krediyi zaten `images.py` IGDB'den yazıyor,
`to_render_spec` de küçük harfe çeviriyor.

**Ders:** karta basılmayan bir alan üslup denetimine girerse, filtre LLM'i
o alanı boşaltmaya iter ve arıza hata olarak değil **eksik özellik** olarak
görünür.

### Instagram gönderi metni (caption)
`write.py` artık `caption` da üretiyor - **aynı çağrıda**, ek LLM maliyeti
yok. `style.py` denetiminden geçiyor, yani üslup kuralları burada da
geçerli. İstemde "kartlarda yazanı tekrarlama, bağlam ver" kuralı var.
En fazla 2 hashtag.

Faz 6 gelmeden de işe yarıyor: `/bana` ile kartları alırken caption
**ayrı bir mesaj olarak** düşüyor, tek dokunuşla kopyalanıyor.

### Metin üslubu — `style.py` filtresi
Deterministik, LLM çağırmaz. Yakaladıkları:
em-dash ve eğik tırnak · yasak kelime listesi (işte, peki, devrim
niteliğinde, çığır açan, adeta, tam anlamıyla, sonuç olarak, yapay zeka
destekli) · emoji · büyük harf · 2'den fazla hashtag · üçlük kalıbı
(a, b ve c) · soru cümlesiyle başlama (son sayfa hariç) · **işaretsiz
Türkçe** (60+ karakterlik metinde hiç ı/ş/ğ/ü/ö/ç yoksa) · yanlış Türkçe ek.

Ek hataları yeniden üretim istenmeden **otomatik düzeltiliyor**
(`autofix_suffixes`): godot'yu → godot'u, steam'da → steam'de vb.

Yazım modu her üretimde rastgele seçiliyor: gözlem / karşılaştırma /
tarihsel not / sayısal detay / karşı görüş. Sabit açılış kalıbını engelliyor.

---

## 6. Dosya yapısı

```
src/
  feeds.json    25 kaynak (18 aktif), her adres elle yoklandı
  fetch.py      RSS tara, kümele, tekrar filtresi
  tier.py       kademe hesabı (kod, LLM değil)
  write.py      Gemini + istem + yeniden üretim döngüsü
  style.py      üslup filtresi, deterministik
  images.py     IGDB görsel seçimi ve indirme
  render.py     HTML sablonu → PNG (--sheet ile görsel havuzu ızgarası)
  telegram.py   mesaj yolla, komut oku, kararı kaydet
  respond.py    kararı uygula + posta bağlı olmayan istekleri icra et
  produce.py    tüm zinciri süren orkestratör
  menu.py       aday menüsü: tier + görsel durumu + LLM önerisi
  apicheck.py   anahtarları canlı yokla, süre ve kota durumu
  publish.py    [YOK — Faz 6]
templates/      card.html + card.css (tasarım burada, SABİT)
fonts/          Bricolage Grotesque, Outfit, OFL.txt
assets/         placeholder.png (anahtarsız render denemesi için)
examples/       sample_post.json (güncel şema, anahtarsız test)
state/          posted / pending (kuyruk) / tg_offset / weekly
                drafts/<id>.json — her postun kendi taslağı
                candidates.json ve img/ git dışı
.github/workflows/   [BOŞ — Faz 7]
```

---

## 7. Anahtarlar ve servisler

`.env` (yerel, git dışı) ve GitHub Secrets'ta aynı beş değer:
`GEMINI_API_KEY` · `IGDB_CLIENT_ID` · `IGDB_CLIENT_SECRET` ·
`TG_BOT_TOKEN` · `TG_CHAT_ID`

| Servis | Not |
|---|---|
| Gemini | ⚠️ **Günde 20 istek** (ölçüldü, aşağıya bak). Model **`gemini-3.6-flash`, sürüm sabit.** 3.7 ısrarla 503 dönüyordu. `gemini-2.5-*` yeni kullanıcılara kapalı. Ücretsiz katman, fatura hesabı bağlı değil, ücretlendirilme mümkün değil |
| IGDB | Twitch üzerinden. Uygulama jetonu her çalışmada yeniden alınıyor. **Twitch, 2FA açık olmayan hesaba uygulama kaydettirmiyor** |
| Telegram | Bot `@questpostinstagram_bot`, chat id `.env` içinde |
| GitHub Actions | Public repo, sınırsız dakika |

### ⚠️ Gemini günlük kota: 20 istek (2026-08-29 ölçüldü)
İnternetteki "ücretsiz katman 1500 istek/gün" bilgisi bu modele UYMUYOR.
429 hatasının gövdesindeki gerçek değer:

    GenerateRequestsPerDayPerProjectPerModel-FreeTier | deger: 20

Bu, LLM'i daha çok kullanma fikrini doğrudan sınırlıyor. Bütçe:

| İş | Çağrı/gün |
|---|---|
| Menü (günde 3 kez) | 3 |
| Post üretimi (3 post × 1-3 deneme) | 3-9 |
| **Toplam** | **6-12** |
| Kalan | 8-14 |

Sığanlar: metin QA (+3). **Sığmayanlar:** kart QA / vision (+15),
görsel-sayfa eşleştirme (+3).

Bu yüzden `caption` ayrı çağrı DEĞİL, ana üretim çağrısına eklendi -
ek maliyeti sıfır. Yeni bir LLM işi eklenecekse önce "mevcut bir çağrıya
sığar mı" diye sorulmalı.

Kotayı ölçmenin yolu: 429 gövdesindeki `violations[].quotaValue`.
Tahmin etme, oku.

### ⚠️ Kota MODEL BAŞINA — işler modellere bölündü (2026-08-29)
Kota adı `GenerateRequestsPerDayPerProjectPerModel` diyor ve gerçekten
öyle: `gemini-3.6-flash` tükenmişken `gemini-3.1-flash-lite` çalışıyordu
(ölçüldü). Yani her modelin ayrı 20 hakkı var.

⚠️ **Limitler eşit DEĞİL.** AI Studio'daki "Gemini API Rate Limit"
panelinden okundu (Project seçicisinden doğru proje seçilmeli):

| Model | RPD (günlük istek) |
|---|---|
| `gemini-3.6-flash` | **20** |
| `gemini-3.5-flash-lite` | **500** |
| `gemini-2.5-flash` | 20 (zaten 404 veriyor) |

| İş | Model | Neden |
|---|---|---|
| Post metni (`write.py`) | `gemini-3.6-flash` | **Sürüm sabit** - model değişirse üslup değişir, 300. post 1. postla aynı olmaz |
| Menü + QA (`HELPER_MODEL`) | `gemini-3.5-flash-lite` | Yardımcı işler. 500'lük havuz, üretim bütçesini yemiyor |

Kazanç sadece "ayrı havuz" değil, **25 kat daha geniş havuz**. QA bu yüzden
açılabildi. Yeni bir LLM işi eklenecekse önce HELPER_MODEL'e bakılmalı.

Panelde bir modelin görünmesi **çağrılabildiği anlamına gelmiyor**:
`gemini-2.5-*` panelde var, `models.list` çıktısında var, ama çağrılınca
404 dönüyor. Yeni model seçerken canlı çağrıyla doğrula.

⚠️ **Bu, çoklu HESAP açmakla karıştırılmamalı.** Kotayı aşmak için ikinci
Google hesabı/projesi açmak ToS ihlali ve zaten işe yaramıyor - kota hesap
katmanı bazında da uygulanıyor. Farklı MODEL kullanmak Google'ın kendi
kota yapısı; aynı hesap, aynı proje.

⚠️ `gemini-2.5-*` modelleri `models.list` çıktısında görünüyor ama
çağrılınca **404** dönüyor. Listede olması erişilebilir olduğu anlamına
gelmiyor.

### Metin QA — varsayılan AÇIK
`style.py` deterministik ve yazım hatası yakalayamıyor (bir üretimde
"dusunceleinizi" karta basılmıştı). `llm_review` ikinci göz oluyor,
`HELPER_MODEL` üzerinde çalışıyor - üretim bütçesini yemiyor.
`--no-qa` ile kapatılır.

Karar kümesi **sınırlı**: `yazim` / `kaynak_disi` / `anlamsiz`. Üslup
yorumu ve "daha iyi olabilir" açıkça yasaklandı - serbest bırakılan model
her metinde bir şey bulur ve her post boşuna yeniden yazdırılır.
Ayrıca gözlem-önce: modelden önce metni özetlemesi isteniyor.

Ölçüldü: kasıtlı bozuk metinde "47 farklı canavar türü" (kaynakta yok) ve
"dusunceleinizi" (yazım) yakalandı; temiz metinde **0 sorun** dedi, yani
yanlış alarm vermedi. Kusursuz değil - aynı cümledeki "gelistirci"
hatasını kaçırdı.

Sorunlar mevcut `problems` kanalından geri besleniyor, ayrı bir mekanizma
yok. Model cevap vermezse boş liste dönüyor: QA'nın kendisi üretimi
durdurmamalı.

### ⚠️ Gemini erişim engeli — çözüldü, tekrar yaşanırsa
İlk Google hesabında tüm modeller `403 PERMISSION_DENIED — Your project has
been denied access` döndü. Elenenler: model ailesi, endpoint sürümü, anahtarın
gönderilme şekli, yeni Cloud projesi, API'yi enable etmek, anahtarı servis
hesabına bağlamak — **hiçbiri işe yaramadı.**

**Engel projeye değil hesaba bağlıydı.** Başka bir Google hesabıyla ilk
denemede çalıştı. Bir daha benzer duvara çarpılırsa **ilk denenecek şey hesap
değiştirmek**, proje ayarlarıyla uğraşmak değil. Eski/yerleşik hesap tercih
edilir; sıfır hesaplar "yeni hesap" filtresine takılabiliyor.

Ayrıca: **AI Studio sohbeti ile Gemini API iki ayrı kapı.** Sohbetin
çalışması API'nin çalışacağı anlamına gelmiyor.

---

## 8. Telegram komutları

### ⚠️ Kuyruk çok girdili (2026-08-29)
`pending.json` artık tek slot değil, `{"kuyruk": [...]}`. Sebep: acil haber
geldiğinde onay bekleyen normal post **ertelenmesin**, ikisi yan yana dursun
(kullanıcı kararı). En fazla `MAX_KUYRUK = 3` post bekleyebilir.

Her postun kendi taslağı var: `state/drafts/<id>.json`. Tek `draft.json`
kalsaydı ikinci post birincinin metnini ezerdi. `id` = `YYYYAAGG-oyun-adi`,
kart klasörüyle aynı.

**Komutun adresi** şu sırayla çözülür:
1. Komut bir postun kart mesajına **yanıt** olarak yazılmışsa → o posta gider
   (`reply_to_message.message_id`, albümdeki hangi kart olursa olsun)
2. Yanıt yoksa ve bekleyen **tek** post varsa → ona gider (tek post varken
   deneyim hiç değişmiyor, olağan hâl bu)
3. Yanıt yoksa ve **birden fazla** post bekliyorsa → bot uygulamaz, "hangisi?"
   diye sorar ve kuyruğu listeler. Yanlış posta `/iptal` uygulanmasındansa
   bir kez fazla sorulsun.

Eski tek slotlu biçim `load_queue()` içinde hâlâ okunuyor (geçişte elde post
kalmasın diye).

### Komut alındı bildirimi (ack)
Bot cron ile uyandığı için kullanıcı komutu yazıp bekliyor. Uyandığında önce
"gördüm, çalışıyorum" diyor: `telegram.py` içindeki `ACK` sözlüğü, komut
okunur okunmaz. Kuyrukta birden fazla post varsa mesajın başına
`[oyun adı]` konuyor.

⚠️ **Sınırı bilinerek kabul edildi:** bot uyumadan mesaj atamaz. Ack, komutu
yazdıktan sonra değil, **botun uyandığı anda** gelir. Cron gecikmesi (5-30 dk)
bu şekilde kapanmıyor; ack sadece "uyandım, işlemi başlattım" der.

### ⚠️ Ana akış değişti (2026-08-29): önce menü, sonra üretim
Bot artık kendi seçtiği haberi doğrudan üretmiyor. `menu.yml` günde 3 kez
(11:10 / 17:10 / 20:10 TRT) adayları listeliyor, kullanıcı `/uret <numara>`
yazınca üretim başlıyor. **`produce.yml`'in cron'u kaldırıldı**, sadece elle
tetikleme için duruyor.

Gerekçe: görselsiz veya ilgisiz bir haber için LLM ve render bedeli boşa
gidiyordu; karar kullanıcıya öne alındı. Bedeli: kullanıcı seçmezse o turda
post üretilmiyor — bilinçli.

Menüde üç bilgi bir arada:
- **tier** — KOD hesaplar, LLM değil (kart rengi buna bağlı)
- **görsel durumu** — IGDB'de gerçekten kaç kullanılabilir görsel var
  (metin üretilmeden önce bakılıyor)
- **⭐ öneri** — LLM, tek soru: *"Instagram gönderisi olarak görünürlük
  açısından ilginç mi"*

⚠️ **LLM'e verilen bütçe sınırlı: tam olarak 1 aday seçmek zorunda.** Serbest
bırakılırsa hepsini işaretler ve öneri değersizleşir — `tier.py`'nin "LLM'e
serbestlik verilirse her haberi S yapar" dersi burada da geçerli. İstemde
açıkça yazılı: *"Birden fazla öneremezsin. Hiçbirini öneremem diyemezsin."*
**Öneri tier'a dokunmaz**, ayrı bir sinyaldir; kullanıcı zaten `/c /b /a /s`
ile kademeyi elle ezebiliyor.

İlk ölçüm: 6 adaydan Squadron 42 seçildi, gerekçe *"gta 6'yı suçlamaları
yüksek etkileşim ve yorum potansiyeli yaratıyor"* — tüm adaylar B kaldı,
yani LLM tier'ı şişirmedi.

### Posta bağlı olmayan istekler
`/konular`, `/uret`, `/apideadline` bir posta ait değil; kuyruk post bazlı
olduğu için oraya sığmıyorlar. `telegram.py` bunları `state/istek.json`'a
yazıyor, `respond.py` icra edip dosyayı **hemen siliyor** — cron 5 dakikada
bir çalıştığı için kalan bir istek her turda yeniden üretim tetiklerdi.

| Komut | Ne yapar |
|---|---|
| `/konular` | Kaynakları tarar, aday menüsünü yollar |
| `/uret 2` | Menüden seçileni üretir. Menü yoksa, numara geçersizse veya aralık dışıysa reddediyor |
| `/apideadline`, `/api` | Anahtar durumu: 🟢 çalışıyor · 🟡 süre yaklaştı veya kota sınırı · 🔴 çalışmıyor / doldu |
| `/ok`, `/otomatik` | Onayla. Faz 6 yokken kullanıcıya `/bana` öneriliyor, kuyruk **açık kalıyor** (temizlense post kaybolurdu) |
| `/kuyruk` | Bekleyen postları listeler |
| `/bana` | Kartları **sıkıştırılmamış dosya** olarak yollar (`sendDocument`). Telegram fotoğrafları yeniden sıkıştırıyor |
| `/iptal` | Postu at, kuyruğu boşalt |
| `/yeniden` | Metni baştan yazdır, kartları bas, tekrar sor |
| `/c /b /a /s` | Kademeyi ez, kartları yeni renkle bas |
| `/gorsel` | Aynı oyundan **başka bir set** dene (havuzu kaydırır) |
| `/gorsel 4 7 2` | Sayfa sayfa kesin seçim |
| `/havuz` | Havuzdaki tüm görselleri **numaralı ızgarada** yollar (tip + gerçek boyut yazılı) |
| `/start /help` | Komut listesi |

`state/tg_offset.json` aynı komutun iki kez işlenmesini önlüyor —
`respond.yml` 5 dakikada bir çalışacağı için şart.

---

## 9. Öğrenilen dersler (tekrar etmemek için)

**LLM istemin üslubunu taklit ediyor.** İlk gerçek çıktı Türkçe karakterler
olmadan geldi ("ayni", "hazirlaniyor") çünkü istem ASCII Türkçesiyle
yazılmıştı. İstem kusursuz Türkçe olmak zorunda.

**Komut listesini göstermek, o komutu yazmak değildir.** Faz 5'te altı komut
listelendi ama sadece ikisi çalışıyordu; kararı uygulayan kod yoktu.
Arayüz eklerken önce icra tarafı yazılmalı.

**Kullanıcının erişemediği bilgi arayüz olamaz.** `/gorsel 1 3 5` teknik
olarak çalışıyordu ama havuzu göremeyen kullanıcı numara veremezdi.
`/havuz` bu yüzden var.

**Vision QA "bu iyi mi" diye sorulunca işe yaramıyor.** Bozuk bir kart
(görsel %25'e inmiş, krem %75) modele soruldu, "tamam" dedi. Aynı kart
sayısal kriterli ve önce gözlem yaptıran istemle sorulunca doğru yakalandı.
**Ölçülebilir kriter + gözlem-önce şart.** Ayrıntı: bölüm 11.

**Windows'ta üretilen state Linux'ta okunuyor.** `pending.json` yolları
ters bölü ile yazılıyordu; Actions'ta sessizce çalışmazdı. Yol yazarken
`as_posix()`.

**IGDB görsel boyutları uçurum gibi değişiyor.** Aynı oyunun görselleri
600x338 ile 10681x7874 arasında. Filtre olmadan bulanık kart basılıyordu.
Ayrıca IGDB kapak metadata'sı küçük boyut raporluyor ama `t_original`
çok daha büyüğünü veriyor.

**Windows konsolu cp1254.** Betiklerin başında stdout/stderr utf-8'e
çevriliyor, yoksa Türkçe başlık basarken çöküyor.

**Bash heredoc kaçış karakterlerini bozuyor.** Python dosyalarına metin
yazarken düzenleme aracı kullanılmalı, heredoc değil.

**Satır içi stil enjekte edilen CSS'i ezer.** `--tier` değişkeni
`style.setProperty` ile basıldığı için stylesheet'ten değiştirilemiyor.

---

## 10. Ayarlanabilir eşikler

| Dosya | Sabit | Değer | Ne yapar |
|---|---|---|---|
| `fetch.py` | `CLUSTER_THRESHOLD` | 0.30 | IDF ağırlıklı başlık benzerliği |
| | `MIN_SHARED_IDF` | 3.0 | paylaşılan kelimelerin kanıt kütlesi |
| | `BRIDGE_DF` / `BRIDGE_THRESHOLD` | 2 / 0.15 | özel isim köprüsü |
| `tier.py` | `SOURCE_TIERS` | 4→S, 3→A, 2→B, 1→C | kademe tabanı |
| | `DISTINCTIVE_WEIGHT` | 1.2 | ayrıştırıcı kaynak eşiği |
| `images.py` | `NAME_MATCH_MIN` | 0.55 | oyun adı benzerliği |
| | `MIN_IMAGE_WIDTH/HEIGHT` | 1280x720 | görsel çözünürlük tabanı |
| `write.py` | `DEFAULT_MODEL` | gemini-3.6-flash | sürüm sabit |
| | `MAX_ATTEMPTS` | 3 | üslup filtresi yeniden üretim |
| `render.py` | `SCALE` | 4/3 | 1080x1350 → 1440x1800 |
| `card.html` | `FADE` / `BREATH` | 330 / 38 px | gradyan geçişi |

Kümeleme geçmişi: düz Jaccard hiç birleştirmiyordu; "nadir kelime zorunlu"
kuralı **büyük haberleri eliyordu** (çok kaynak yazınca kelime sıklaşıyor).
Çalışan hâl: IDF oranı + kanıt kütlesi + özel isim köprüsü.
Ölçüm: 701 kayıt → 221 pencerede → 193 küme, 13'ü çok kaynaklı.

---

## 11. Sıradaki işler — detay

### Faz 7 · workflow'lar
- `produce.yml` — cron günde 3 kez, `produce.py` çağırır
- `respond.yml` — cron 5 dk, `respond.py` çağırır
- `watch.yml` — cron 10-15 dk, **sadece `fetch.py`**: patlama tespiti.
  Ölçüt kaç kaynak değil, **ne kadar sürede**: küme içi ilk-son kayıt farkı
  `< 90 dk` ve `source_count >= 3` ise son dakika sayılır, `produce.py --acil`
  tetiklenir. `tier.py` bu sinyali henüz hesaplamıyor, eklenecek.
- `refresh_token.yml` — aylık, Instagram token yenileme (Faz 6'ya bağlı)
- `urgent.yml` — `workflow_dispatch` iskeleti, son dakika haberi
- Playwright/Chromium kurulumu önbelleğe alınmalı, yoksa her çalışmada
  ~120 MB indirilir
- Bot state dosyalarını kendi commit'ler, Actions write izni şart.
  State commit'lerinde `pull --rebase` retry'ı olmalı: `produce` ve `respond`
  aynı anda çalışırsa git çakışır.

### ⚠️ GitHub cron ÇALIŞMADI — tetikleme cron-job.org'a taşındı (2026-08-29)
`respond.yml` ve `menu.yml` push edildikten sonra **2.5 saat boyunca tek bir
`schedule` çalışması olmadı.** Actions kaydında sadece elle atılan
`workflow_dispatch` çalışmaları vardı. Yapılandırma doğruydu: repo public,
default branch `main`, workflow dosyaları uzakta, saatler UTC, repo 4 günlük
(60 gün inaktivite kuralı geçerli değil).

Yaygın çözüm olan **"bir kez elle çalıştır, cron aktifleşir" numarası bu
repoda işe yaramadı** — elle çalıştırdıktan sonra da tetiklenmedi.

**Çözüm: harici tetikleyici.** cron-job.org GitHub API'yi çağırıyor,
`workflow_dispatch` ile workflow'u başlatıyor. Ölçüldü: 17:19, 17:20, 17:25,
17:29 — beşer dakika arayla, hepsi başarılı.

| İş | Ne zaman | URL |
|---|---|---|
| `quest.post respond` | 5 dakikada bir | `.../workflows/respond.yml/dispatches` |
| `quest.post menu` | `10 11,17,20 * * *` (Istanbul) | `.../workflows/menu.yml/dispatches` |

İstek: `POST`, başlıklar `Authorization: Bearer <PAT>`,
`Accept: application/vnd.github+json`, gövde `{"ref":"main"}`.
cron-job.org'un **IMPORT FROM CURL** düğmesi üçünü birden dolduruyor.

**Token:** GitHub fine-grained PAT, **süresiz**, yalnızca `quest.post`
reposunda, yalnızca `Actions: Read and write`. Sızarsa yapabileceği:
workflow tetiklemek (Telegram spam + Gemini kotası tüketmek), çalışma
kaydı okumak. **Yapamayacağı:** Secrets okumak, kod değiştirmek, repo
silmek. Süresiz seçildi çünkü hasar sınırlı ve iptal etmek saniyelik iş
(Settings → Developer settings → Fine-grained tokens → Revoke).

⚠️ **1 dakikalık tetikleme denenmemeli:** her çalışma runner açılışıyla
1-2 dakika sürüyor, `concurrency` grubu bir öncekiler bitmeden yenileri
kuyruğa alıyor ve gecikme **artıyor**. 5 dakika ölçülmüş dengeli değer.

GitHub'ın kendi cron'u workflow dosyalarında **bırakıldı**: bir gün
kendiliğinden çalışırsa çift tetikleme olur ama `concurrency` sıraya
soktuğu için zararsız, yedek görevi görür.

`/apideadline` çıktısındaki **"Tetikleme (Actions)"** satırı bunu
izliyor: son çalışma 30 dakikayı geçerse sarı, 2 saati geçerse kırmızı.
Harici tetikleyici sessizce durursa (token iptal, servis hesabı kapanma,
iş silinme) tek belirti bu olurdu.

### ⚠️ Cron gecikmesi — mimari kısıt, bilinerek kabul edildi
GitHub Actions cron **minimum 5 dakika**; `*/1` yazılırsa sessizce atlanır.
Üstelik 5 dk bile garanti değil: pratikte 5-30 dk gecikme normal, yoğun
saatlerde daha fazla. Yani `/havuz` yazıp 25 dakika beklemek gerçek bir
senaryo.

**Elenen alternatifler (2026-08-29, kullanıcı kararı):**
- *Telegram webhook + Cloudflare Worker*: ücretsiz (100k istek/gün, bizim
  kullanım günde ~200) ve tek seferlik kurulum, ama **kullanıcı istemedi**.
  Ayrıca ölçüldüğünde beklendiği kadar hızlı da değil: Telegram→Worker→GitHub
  dispatch anlık, fakat arkasındaki runner soğuk başlangıcı (kuyruk + checkout
  + pip) ~1-2 dk ekliyor. Yan etkisi: webhook aktifken `getUpdates` **409**
  döner, yani elle `respond.py` çalıştırma bozulur (`deleteWebhook` ile geri
  alınır). Worker ayrıca ikinci bir sır (GitHub PAT) ve ikinci bir platform
  demek; PAT süresi dolarsa bot **hata vermeden** susar.
- *Uzun yoklama (6 saatlik job, `getUpdates timeout=50`)*: saniyeler mertebesinde
  cevap verirdi ve harici servis gerektirmezdi; kullanıcı basitlik için
  cron'da kaldı.

Gecikme kabul edildiği için **ack mesajı** eklendi (bkz. bölüm 8): sistemin
çalıştığını görmenin yolu bu.

### Faz 6 · Instagram
Facebook Sayfası + Meta developer app + hesabı Instagram Tester olarak ekleme.
PNG repoya commit edilip `raw.githubusercontent.com` linki API'ye verilecek
(Graph API dosya yüklemiyor, herkese açık URL istiyor). Uzun ömürlü token
60 günde ölüyor.

Not: Graph API lisanslı müzik eklemeyi desteklemiyor; S kademesi postlarda
`/bana` tercih edilebilir.

### `qa.py` · görsel denetim — tasarım oturdu, artık yazılabilir
Kullanıcının talebi. Kanıtlanmış tasarım:

**Katman 1 — kod (bedava, anında, tutarlı).** `render.py` zaten metin bloğu
yüksekliğini ve krem oranını ölçüyor; eşik koymak yeter. Bozuk kart örneği
krem %78'de yakalanıyordu. Çözünürlük denetimi `images.py` içinde zaten var.

**Katman 2 — vision (kodun göremediği).** Görsel konuya uygun mu, kırpma
tuhaf mı, yabancı logo veya arayüz var mı. Ölçüm: kart başına **1222 token,
~9 saniye**; günde 15 görsel ≈ 18 bin token, ücretsiz katmanın çok altında.

Kurallar: rubrik ayrı dosyada (`templates/qa_rubric.md`) — değiştirmek commit
gerektirsin · `temperature 0` · **sınırlı karar kümesi** (`tamam` /
`metin_kisalt` / `gorsel_degistir` / `elle_bak`), model çözüm uyduramasın ·
kararlar `state/qa_log.json` içine yazılsın · **en fazla 2 düzeltme turu**,
sonra "bot 2 kez denedi" notuyla Telegram'a gitsin.

Ayrıca metin QA düşünülebilir: üslup filtresi yazım hatası yakalayamıyor
(bir denemede "düşüncelerinizi" yerine "dusunceleinizi" çıktı).

### Esnek sayfa sayısı — KULLANICI İSTEMİ BEKLİYOR
Şu an `write.py` istemi "3-5 sayfa" diyor. Kullanıcı bunun esnemesini
istiyor: **flash haber tek sayfa, derin haber 8-10 sayfa.** Sayfa göstergesi
ve `render.py` zaten esnek (`1/1`, `1/10` sorunsuz çalışıyor); değişecek olan
tek şey istemdeki sayfa sayısı kuralı ve hangi haberin kaç sayfa hak ettiğine
dair yönerge. **Kullanıcı bu istemi kendisi verecek.**

---

## 12. Bilinen sınırlar ve açık maddeler

- **Otomasyon arzı çözer, dağıtımı çözmez.** Hesap yeni, ilk aylarda erişim
  düşük olacak. Büyümeyi haber değil evergreen içerik sağlar.
- Elle 3-5 post atma tavsiyesi **kullanıcı tarafından bilerek atlandı**
  (deney amaçlı, risk kabul edildi).
- Kümeleme tek dilde çalışıyor. TR kaynaklar `feeds.json` içinde
  `enabled: false` — karışık dilde "kaç kaynak yazmış" sinyali bozuluyordu.
- Kaynak sayısı haberin **yaygınlığını** ölçüyor, **ilginçliğini** değil.
  4 kaynağın yazdığı "gamescom nasıl izlenir" rehberi S çıkıyor. Rahatsız
  ederse kategori bazlı düzeltici eklenebilir.
- Tam makale metni çekilmiyor, kümedeki kaynakların RSS özetleri
  birleştiriliyor (kazıma yapmamak için bilinçli tercih).
- Steam yeni çıkanlar için RSS yok, ayrı modül gerekir. TR stüdyo duyuruları
  için ortak besleme yok.
- **Twitter/X kaynak olarak — Faz 7'den sonraya ertelendi (kullanıcı kararı).**
  Ücretsiz okuma katmanı yok: Şubat 2026'da kullanım başına ödemeye geçildi,
  **okuma başına $0.005**, eski $200/ay Basic yeni kayıtlara kapalı. 20 hesabı
  15 dk'da bir taramak ≈ günde $48. Ücretsiz yollar (RSS köprüleri, üçüncü
  parti scraping API'leri) `feeds.json` şemasına dokunmadan oturur ama
  kırılgan. Tasarım kararı: **Twitter kaynak değil, erken uyarı sensörü
  olmalı** — viral tweet doğrudan post olmaz, bot RSS'te doğrulama arar,
  bulamazsa Telegram'a *post değil bildirim* gönderir. `tier.py` içindeki
  `kinds == {"community"} -> C` kuralı zaten bunu söylüyor, korunacak.
  Gerekçe: viral olmak doğru olmak değil, ve viral tweetin görseli
  "görseller yalnızca IGDB'den" telif kuralını deler.
- Evergreen içerik (`/evergreen <konu>`) ve haftalık C derlemesi
  (`state/weekly.json` doluyor) henüz üretilmiyor.
- Kart dokusu (grain, hafif baskı kayması) düşünülmüştü, yapılmadı.
- `telegram.py` içindeki `TIER_LABELS` ile `render.py` içindeki `TIERS`
  ayrı duruyor; kademe adı iki yerde. Değiştirilirse ikisi de güncellenmeli.
- `out/` klasörü repoya commit edilir (Instagram'ın herkese açık URL şartı).
  Şu an boş; üretim çalıştıkça `YYYYAAGG-oyun-adi/` klasörleri birikecek.

---

## 13. Doğrulama komutları

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium

py -3.12 src/fetch.py --print
py -3.12 src/tier.py
py -3.12 src/render.py examples/sample_post.json --out out/deneme
py -3.12 src/write.py --list-models
py -3.12 src/produce.py --dry-run
py -3.12 src/respond.py
```

İlk üçü anahtarsız çalışır. `--dry-run` Telegram'a yollamaz.
