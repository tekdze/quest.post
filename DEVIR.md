# DEVIR NOTU — quest.post

> Yeni sohbete geçerken **önce bunu oku.** Kararlar burada, kodda değil.
> Önemli bir karar alındığında burası güncellenir.

Son güncelleme: 2026-08-30 · **Sistem çalışıyor, ilk gönderi yayınlandı.**
Bugün eklendi: esnek sayfa sayısı (bkz. bölüm 4).

---

## 1. Proje

Türkçe oyun haberleri paylaşan yarı otomatik bir Instagram içerik hattı.

**Hesap:** `@quest.post` · **Dil:** Türkçe, tamamen küçük harf
**Format:** 1080x1350 tasarım, 1440x1800 çıktı (4:5 carousel)

### Tasarım felsefesi
"AI ürünü görünmemek" birincil kısıt. Teknik karşılığı: **LLM tasarıma
dokunmaz.** Şablon sabit HTML/CSS, kademeyi kod hesaplar, görseli kod seçer.
LLM yalnızca metin yazar ve veri üretir.

### İş bölümü
- **Claude:** Python, HTML/CSS, workflow YAML, commit
- **Kullanıcı:** hesap/anahtar açma, Secrets girme, Telegram'da onay, geri bildirim
- **Anahtarlar asla sohbete yazılmaz** — sadece `.env` (git dışı) ve GitHub Secrets

---

## 2. Sistem nasıl çalışıyor

### Günlük akış
| Saat (TR) | Ne olur |
|---|---|
| 11:10 · 17:10 · 20:10 | `menu.yml` — aday menüsü Telegram'a düşer |
| her 5 dk | `respond.yml` — komutları işler |
| ayın 1'i | `refresh_token.yml` — Instagram jetonunu tazeler |

Menüden `/uret <numara>` → metin yazılır, görsel seçilir, kartlar basılır →
onaya gelir → `/ok` Instagram'a gönderir.

Komuta yanıt **~6-7 dakikada** gelir (5 dk tetikleme + runner açılışı).
Bot komutu görür görmez "işleme alındı" mesajı atıyor.

### Boru hattı
```
fetch.py     RSS tara, kümele, tekrarları ele   → state/candidates.json
tier.py      kademe hesabı (KOD, LLM değil)
menu.py      aday menüsü: tier + görsel durumu + LLM önerisi
write.py     Gemini → Türkçe metin + caption    → state/drafts/<id>.json
style.py     üslup filtresi + LLM ikinci gözü
images.py    IGDB → görsel seç, indir, kredi    → state/img/
render.py    HTML → Chromium → PNG              → out/<id>/
telegram.py  kartları yolla, komutu kaydet      → state/pending.json
respond.py   kararı uygula, istekleri icra et
publish.py   Instagram'a carousel olarak yayınla
apicheck.py  anahtarları canlı yokla
```
Her aşama **ayrı süreç**: Actions kaydında patlayan aşama tek bakışta görünsün.

### Telegram komutları
| Komut | Ne yapar |
|---|---|
| `/konular` | Günün adaylarını listeler (özet + görsel durumu + ⭐ öneri) |
| `/uret 2` | Seçileni üretir |
| `/ok` | Onayla, Instagram'a paylaş |
| `/bana` | Kartları dosya olarak yolla (caption ayrı mesajda) |
| `/yeniden` | Metni baştan yazdır |
| `/iptal` | Postu at (bir daha aday olmaz) |
| `/havuz` · `/gorsel` · `/gorsel 4 7 2` | Görsel değiştirme |
| `/c /b /a /s` | Kademeyi elle ez |
| `/kuyruk` · `/apideadline` | Durum |
| `/komutlar` | Tam rehber |

⚠️ Komutlar `telegram.py` içindeki **`KOMUT_REHBERI`** listesinden üretiliyor.
Yeni komut eklerken sadece oraya yazılır.

### Kuyruk kuralları
- `pending.json` çok girdili (`{"kuyruk": [...]}`), en fazla 3 post
- **Onay bekleyen normal post varken yeni üretim yapılmaz** — acil etiketli
  postlar bu kuraldan muaf
- Komutun hangi posta gittiği: önce **yanıt** (reply), yoksa bekleyen tek
  posta, birden fazlaysa bot "hangisi?" diye sorar
- Her postun kendi taslağı: `state/drafts/<id>.json`

---

## 3. Tasarım sistemi — SABİT

Kararlar konsept turlarıyla alındı. Değiştirmeden önce gerekçeyi oku.

### Fontlar
`fonts/` altında, OFL, variable: **Bricolage Grotesque** (başlık, w800) ·
**Outfit** (gövde, 300-500). `@font-face` içinde `format("truetype-variations")`
ve ağırlık aralığı şart.

### Renkler ve kademe
| Rol | Hex | | Kademe | Ad | Renk |
|---|---|---|---|---|---|
| Krem | `#F1EDE3` | | C | sıradan | `#4A4A4A` |
| Mürekkep | `#17151A` | | B | büyülü | `#2A6398` |
| Gövde | `#3B372F` | | A | sıradışı | `#6A4CA6` |
| İkincil | `#8A8378` | | S | mitik | `#D9741F` |
| Ayraç | `#CFC8B8` | | | | |

Kademe rengi kartta üç yerde: sol dikey şerit (28px), kademe kutusu, madde
işaretleri. Son sayfada dördüncü: künye bandı.

⚠️ **Tier renginin üstüne her zaman KREM yazı gelir.** S'de kontrast 2.78
(sınır 4.5). Koyu yazı ve turuncuyu koyulaştırmak denendi; kullanıcı
**kavram bütünlüğü için** krem yazıda karar kıldı. Bilinçli ödün.

### Kart anatomisi
- Arka planda oyun görseli, tam kanama, `object-position: 50% 25%`
- Alttan krem gradyan; başlangıcı sabit değil, `card.html` içindeki
  `fitScrim()` metin yüksekliğine göre hesaplıyor
- Ölçülen krem alan: kapak %47 · metin %36-40 · son sayfa %50
- Metin gölgesi/konturu **yok**, okunurluk gradyanla
- Üstte 170px ince karartma (aydınlık gökyüzünde köşe bilgileri okunmuyordu)
- Kapakta iki kutu: kademe (tier renginde) + tür (mürekkep). **Köşe
  yuvarlatma yok** ("AI slop"), genişlik metne göre

### Sayfa tipleri
**kapak** (kademe + tür kutusu + başlık) · **metin** (başlık + paragraf +
2-3 madde) · **rakam** (sayı 92px, açıklama 32px) · **son sayfa** (soru +
tek çağrı kutusu + künye bandı)

Sayfa **sayısı** sabit değil (1-10, bkz. bölüm 4). Düzen sabit: ilk sayfa
kapak, son sayfa (birden uzunsa) son sayfa, en fazla bir rakam sayfası.
**Tek sayfalık postta künye yok** — künye bandı yalnızca son sayfada duruyor
ve tek sayfalıkta o sayfa hiç basılmıyor. Bilinçli karar: flaş haberde tek
kartın sadeliği, marka bandını sıkıştırmaktan iyi.

### Tipografik mod
Görsel bulunamayan haberlerde: görsel ve gradyan gizlenir, içerik dikeyde
ortalanır, kapak başlığı 104px'e çıkar. Temsili görsel geldiğinden beri
nadiren tetikleniyor.

### ⚠️ Açık tasarım sorunu
**Sol tier şeridi profil ızgarasında görünmüyor.** Instagram ızgarada kartı
yanlardan kırpıyor. Kademe kutusu görünmeye devam ediyor, yani renk tamamen
kaybolmuyor. Karar verilmedi. Ölçüt: çözüm kart tek başına açıldığında da
bozulmamalı.

---

## 4. İçerik kuralları

### Telif — tartışılmaz
- Görseller **yalnızca IGDB'den** (resmi stüdyo materyali)
- Kredi **IGDB'nin şirket verisinden**, LLM tahmininden değil
- **Kredi sayfa başına**: seri yedeğinden gelen görselin stüdyosu farklı
  olabiliyor (Pokémon TCG Pocket ≠ ana seri). Tek ortak kredi basmak o
  sayfada yanlış stüdyoyu göstermek olurdu
- **Sızıntı haberinde de görsel kullanılır** (karar 2026-08-30, değişti).
  Eskiden `is_leak` bütün görselleri kaldırıyordu ve sızıntı postları
  tipografik basılıyordu. Gerekçe "sızan materyali yeniden yayımlamayalım"dı
  ama kural gerekçesinden genişti: görseller **zaten yalnızca IGDB'den**,
  yani resmi stüdyo materyalinden geliyor. `is_leak` artık sadece kartın
  kategori etiketini ("sızıntı") belirliyor.
  ⚠️ Kabul edilen risk: duyurulmamış bir oyunun IGDB kaydındaki iki üç görsel
  sızıntının kendisinden gelmiş olabilir. Bilinçli ödün.
  ⚠️ İstem de değişti: modele "sızıntıda görsel kullanılmayacak" denince
  görsel alanlarını (`image_candidates`, `representative_games`) **boş
  bırakıyordu**. Kural kalkarken o cümle de düzeltilmek zorundaydı, yoksa
  engel kalkar ama aday listesi boş gelir.

### Görsel seçim sırası (`images.py`)
1. `search_name` — haberin asıl konusu olan oyun
2. `image_candidates` — metinde **adı geçen** oyunlar, LLM'in sırasıyla,
   ilk **yeterli** olan (yeterli = sayfa sayısı kadar görsel)
3. `series_fallback` — aynı serinin zengin oyunu, havuz yetmezse tamamlar
4. `representative_games` — haberde adı geçmese de konuyu temsil eden oyun
   (konsol/şirket haberleri için). LLM bağı kendi kurar, konu konu kural yok
5. Hiçbiri tutmazsa tipografik

⚠️ **Kapak ASLA yedekten/temsiliden seçilmez.** İlk kart vitrindir, orada
haberin konusu olmayan bir oyun okuru yanıltır.

### Metin üslubu — `style.py`
Deterministik, LLM çağırmaz. Yakaladıkları: em-dash, eğik tırnak, yasak
kelimeler (işte, peki, devrim niteliğinde, çığır açan, adeta, sonuç olarak,
yapay zeka destekli), emoji, büyük harf, 2'den fazla hashtag, üçlük kalıbı
(a, b ve c), soru cümlesiyle başlama, **işaretsiz Türkçe**, yanlış Türkçe ek.
Ek hataları ve büyük harf otomatik düzeltiliyor (`autofix_suffixes`,
`autofix_lowercase`).

⚠️ **Mekanik hatada yeniden üretim istemek kotayı yakıyor.** Ölçüldü
(2026-08-31): bir üretim üç denemede düştü, ikisi sırf `game` alanı
büyük harfle geldiği için ("Total War: Warhammer 40,000"). Kural mutlak
olduğu için düzeltmesi de mekanik - reddetmek yerine küçük harfe
çevriliyor. Ölçüt: kural mutlaksa ve düzeltme belirsizlik taşımıyorsa
filtre düzeltir, modeli yeniden çalıştırmaz.
`tr_lower` "I" harfini "i"ye çeviriyor, "ı"ya değil: karta basılan
büyük harfli kelimeler neredeyse hep İngilizce oyun adı ("Iron Man").

⚠️ **Yedek model kart metni için güvenilir değil.** `flash-lite`
işaretsiz Türkçe yazıyor ("temali", "on incelemeler") ve üslup
filtresine takılıyor; ham çıktıda ölçüldü, düzeltme aşamasıyla ilgisi
yok. Yani ana modelin kotası dolduğunda yedeğe düşmek çoğu zaman post
üretmiyor, sadece üç deneme harcıyor. Diakritik geri koymak sözlük işi.

Yazım modu her üretimde rastgele seçiliyor (gözlem / karşılaştırma / tarihsel
not / sayısal detay / karşı görüş) — sabit açılış kalıbı oluşmasın.

⚠️ **Karta basılmayan alanlar `NON_PROSE_KEYS`'e girmeli.** `search_name`,
`image_candidates`, `series_fallback`, `representative_games`, `studio`
İngilizce oyun adları ve
büyük harf içermek zorundalar. Denetime girdiklerinde filtre LLM'i o alanları
**boşaltmaya itiyor** ve arıza hata olarak değil *eksik özellik* olarak
görünüyor.

### Metin QA (`llm_review`) — varsayılan açık
`style.py` yazım hatası yakalayamıyor. LLM ikinci göz oluyor, karar kümesi
**sınırlı**: `yazim` / `kaynak_disi` / `anlamsiz`. Üslup yorumu ve "daha iyi
olabilir" açıkça yasak — serbest bırakılan model her metinde bir şey bulur ve
her post boşuna yeniden yazdırılır. `--no-qa` ile kapatılır.

### Rakamlar
Çıktıdaki her rakam kaynak metinde geçmek zorunda, `style.py` denetliyor.

### Post uzunluğu — LLM karar verir, kod sınırlar
Eskiden istem "3-5 sayfa" diyordu: tek cümlelik duyuru da, üç kaynağın
ayrıntı verdiği haber de aynı uzunlukta çıkıyordu. Artık uzunluğu haberin
derinliği belirliyor (1 sayfa flaş → 10 sayfa derin), **sınırları kod
uyguluyor**: `write.check_structure` sayfa sayısını, sıralamayı ve boş alanı
denetliyor, ihlalde yeniden üretim tetikleniyor.

⚠️ Bu, "LLM tasarıma dokunmaz" kuralının **tek istisnası** ve bilinçli:
metnin kaç sayfa sürdüğünü ancak metni yazan bilir. Ama ölçüt modelde,
**sınır kodda** — serbest bırakılırsa her haberi 10 sayfa yapar.

Denetlenenler: 1-10 sayfa · ilk sayfa kapak · birden uzunsa son sayfa outro ·
en fazla bir rakam sayfası · ikinci kapak yok · başlık/metrik/soru/çağrı boş
değil (bunlar eskiden `render.py`'de patlıyordu).

---

## 5. Dosya yapısı

```
src/
  feeds.json    22 aktif kaynak (7 TR kapalı: karışık dil kümelemeyi bozuyor)
  fetch.py      RSS tara, kümele, tekrar filtresi
  tier.py       kademe hesabı (KOD)
  menu.py       aday menüsü
  write.py      Gemini + istem + üslup döngüsü + caption
  style.py      üslup filtresi
  images.py     IGDB görsel seçimi
  render.py     HTML → PNG (--sheet ile havuz ızgarası)
  telegram.py   mesajlaşma, komut kaydı
  respond.py    karar icrası
  produce.py    üretim zinciri
  publish.py    Instagram paylaşımı
  apicheck.py   anahtar durumu
  refresh_token.py
templates/      card.html + card.css (tasarım burada, SABİT)
fonts/          Bricolage, Outfit, OFL.txt
state/          pending (kuyruk) · posted · menu · tg_offset · uyari
                drafts/<id>.json · api_sure.json
                candidates.json ve img/ git dışı
out/            <id>/01.png... — repoya commit edilir (Instagram URL şartı)
.github/        menu · respond · produce · refresh_token + commit-state
```

---

## 6. Anahtarlar ve servisler

`.env` (yerel) ve GitHub Secrets: `GEMINI_API_KEY` · `IGDB_CLIENT_ID` ·
`IGDB_CLIENT_SECRET` · `TG_BOT_TOKEN` · `TG_CHAT_ID` · `IG_ACCESS_TOKEN` ·
`IG_USER_ID`

### ⚠️ Gemini kotası — model başına ve EŞİT DEĞİL
İnternetteki "1500 istek/gün" bilgisi bu modellere uymuyor. Gerçek değerler
AI Studio rate limit panelinden okundu:

| Model | Günlük istek | Kullanım |
|---|---|---|
| `gemini-3.6-flash` | **20** | Post metni. **Sürüm sabit** — model değişirse üslup değişir |
| `gemini-3.5-flash-lite` | **500** | `HELPER_MODEL`: menü, QA, yardımcı işler |

Kota **model başına**, bu yüzden işler bölündü. Ana modelin kotası dolunca
`write.py` yedek modele düşüyor ve Telegram'da *"yedek modelle yazıldı"* notu
görünüyor.

⚠️ Kotayı aşmak için ikinci hesap/proje açmak **ToS ihlali** ve zaten işe
yaramıyor (kota hesap katmanında da uygulanıyor). Farklı model kullanmak
Google'ın kendi yapısı, sorun değil.

⚠️ Bir modelin panelde veya `models.list`'te görünmesi **çağrılabildiği
anlamına gelmiyor** — `gemini-2.5-*` ikisinde de var ama 404 dönüyor. Yeni
model canlı çağrıyla doğrulanmalı.

### Diğer servisler
| Servis | Not |
|---|---|
| IGDB | Twitch üzerinden, uygulama jetonu her çalışmada yenileniyor |
| Telegram | `@questpostinstagram_bot` |
| Instagram | "API with Instagram Login" — **Facebook Sayfası gerekmedi**, App Review de gerekmedi (kendi hesabına tester olarak) |
| GitHub Actions | Public repo, sınırsız dakika |

### ⚠️ Tetikleme cron-job.org'da — GitHub cron çalışmıyor
`schedule` tetikleyicisi bu repoda **hiç çalışmadı** (2.5 saat boyunca sıfır
çalışma, yapılandırma doğruyken). "Bir kez elle çalıştır" numarası da işe
yaramadı. Tetikleme cron-job.org'a taşındı: GitHub API'ye `workflow_dispatch`
POST atıyor. İki iş: **respond** (5 dk) ve **menu** (11:10/17:10/20:10).

Token: fine-grained PAT, süresiz, yalnızca bu repo, yalnızca `Actions: R/W`.
Sızarsa yapabileceği en kötü şey workflow tetiklemek; Secrets okuyamaz, kod
değiştiremez.

⚠️ **1 dakikalık tetikleme denenmemeli:** her çalışma runner açılışıyla 1-2
dakika sürüyor, `concurrency` yenileri kuyruğa alıyor ve gecikme **artıyor**.

⚠️ Yeni iş eklerken **URL'deki workflow adını kontrol et.** Bir kez `menu` işi
`respond.yml`'i tetikledi; tetikleme "başarılı" göründü çünkü GitHub gerçekten
bir workflow çalıştırdı — sadece yanlış olanı.

### ⚠️ Instagram jetonu 60 günde ölüyor
`refresh_token.yml` ayın 1'inde tazeliyor ama **Actions kendi secret'ını
yazamaz**: yeni jeton elle girilmeli. Betik jetonu Telegram'a *yollamıyor*
(sohbete sır düşmesin), sadece "yenile" diyor. Yerelde
`refresh_token.py --goster` ile alınıp Secrets'a yapıştırılıyor.

`/apideadline` hepsini canlı yokluyor: 🟢 çalışıyor · 🟡 süre yaklaştı veya
kota sınırı · 🔴 çalışmıyor. Tetikleyicinin sessizce durduğunu da yakalıyor
(son Actions çalışması 30 dk'yı geçerse sarı, 2 saati geçerse kırmızı).

---

## 7. Önemli notlar — tekrar etmemek için

**LLM istemin üslubunu taklit ediyor.** İlk çıktı Türkçe karakterler olmadan
geldi çünkü istem ASCII Türkçesiyle yazılmıştı. İstem kusursuz Türkçe olmalı.

**LLM'e serbestlik verilirse her şeyi abartır.** Tier'ı belirlese her haberi S
yapar; "bu kart iyi mi" diye sorulunca bozuk karta "tamam" der; öneri sınırsız
bırakılsa hepsini işaretler. Çözüm hep aynı: **sınırlı karar kümesi +
ölçülebilir kriter + gözlem-önce.** Menüdeki "tam olarak 1 aday seç" kuralı bu
yüzden var.

**Komut listesini göstermek, o komutu yazmak değildir.** Bir fazda altı komut
listelendi ama ikisi çalışıyordu. Arayüz eklerken önce icra tarafı yazılmalı.

**Kullanıcının erişemediği bilgi arayüz olamaz.** `/gorsel 1 3 5` çalışıyordu
ama havuzu göremeyen kullanıcı numara veremezdi; `/havuz` bu yüzden var.

**İki ayrı Actions çalışması arasında yalnızca commit edilen dosyalar
taşınır.** `candidates.json` git dışı olduğu için `/uret` "aday bulunamadı"
diye patlamıştı. Çözüm: adayın tam kaydı `menu.json` ile taşınıyor.

⚠️ **Aynı kök sebep üçüncü kez: `/c /b /a /s` de patlıyordu (2026-08-30).**
Tier değişikliği yalnızca "yeniden bas" diyor, `images.py` çalıştırmıyordu.
Ama `state/img/` git dışı: üretimde inen görseller bir sonraki çalışmada
yok ve `render.py` "görsel bulunamadı" diye patlıyordu. Çözüm
`images.py --redownload`: **seçim tekrarlanmıyor**, taslakta yazılı aynı
görsel id'leri geri indiriliyor (yeniden seçilse `/gorsel 4 7 2` ile elle
konan kareler değişirdi). Kimlik dosya adında: `<slug>-<image_id>.jpg`.

### ⚠️ Bildirim döngüsüne karşı üç katman (2026-08-30)
Takılan tek bir post 5 dakikada bir "kartları basarken hata oldu" yolladı,
saatlerce. Sorun tek bir hata değil, **hatanın sonsuz mesaja dönüşebilmesi**.
Üç ayrı yerde kesiliyor, biri delinirse diğerleri tutuyor:

1. **Durum geri alınıyor.** `yeniden_bas_ve_sor` her hata yolunda girdiyi
   `onay_bekliyor`a döndürüyor. Eskiden durum olduğu gibi kalıyor ve her
   respond çalışması aynı işi baştan deniyordu: günde **288 mesaj**.
2. **Aynı uyarı saatte bir kez.** `telegram.hata_bildir` son gönderimi
   `state/uyari.json`'da tutuyor; aynı uyarı `UYARI_SUSTURMA_DK` (60 dk)
   içinde tekrar gelirse yollanmıyor, sayılıyor. Yeniden yollandığında
   "(bu uyarı 47 kez daha tekrarlandı)" ekleniyor - sorun sessizce
   kaybolmuyor, sadece sohbeti boğmuyor. **Hangi koddan gelirse gelsin
   çalışır**, çünkü hatanın kendisini değil tekrarını kesiyor.
3. **Takılan posta ulaşılabiliyor.** Komutlar yalnızca `onay_bekliyor`
   durumundaki postlara gidiyordu; `yeniden_bas`ta kilitlenen post
   Telegram'dan **erişilemez** oluyordu (`/gorsel` -> "onay bekleyen
   post yok", yanıt versen bile ikinci kontrol engelliyordu). Artık
   `/iptal` her durumda geçerli - kilitli postun çıkış kapısı - ve
   diğer komutlar gerçek durumu söylüyor.
4. **Workflow mesajları sabit anahtarlı.** Metinde Actions run numarası
   olduğu için her seferinde farklı görünüyorlardı ve 2. katmana takılmazlardı.
   `telegram.py say --tekrarsiz menu-workflow` sabit kimlik veriyor.

⚠️ **Sebep zincirin dibinden gelmeli.** `respond -> produce -> write`
üç katmanlı ve produce, write'ın hatasını yutup "cikis kodu 1" diyordu:
Telegram'a düşen mesaj sebebi taşımıyordu. `produce.run` artık alt
sürecin son stderr satırını kendi çıkış mesajına koyuyor.

⚠️ **Yarım JSON çökme değil, yeniden deneme sebebi.** Sayfa sayısı 10'a
kadar çıkabildiği için model çıktı sınırına takılıp yarım JSON
döndürebiliyor; eskiden bu traceback'le ölürdü. `GecersizCevap`
yakalanıyor ve modele "daha kısa yaz" denip tekrar deneniyor.
`finishReason` mesaja giriyor: MAX_TOKENS ile SAFETY ayrı sorunlar.

Ayrıca **hata sebebi mesaja giriyor**: `respond.run` alt sürecin son stderr
satırını saklıyor, `sebepli()` onu uyarıya ekliyor. "kartları basarken hata
oldu" cümlesi tek başına hiçbir şey söylemiyordu; sebebi görmek için Actions
kaydını açmak gerekiyordu.

⚠️ **Aynı hata `/yeniden`'de tekrarlandı ve aylarca görülmedi (2026-08-30).**
Komut `write.py --index <n>` çağırıyordu, yani yine `candidates.json`'a
bakıyordu; o dosya runner'da hiç yok. `/yeniden` Actions'ta **hiçbir zaman
çalışmamıştı**, her seferinde "üretim başarısız oldu" diyordu. Yerelde
çalıştığı için fark edilmedi. Çözüm aynı kalıp: adayın tam kaydı artık
taslakta (`_aday`), `write.py --draft` onu okuyor, `candidates.json`
gerekmiyor. **Ders: bir komut yerelde çalışıyorsa Actions'ta da çalışıyor
demek değil — git dışı her dosya orada yok sayılmalı.**
Eski biçim taslaklarda (`_aday` yok) `/yeniden` artık sebebini söylüyor.

**State çakışmasında "en son yazan geçerli".** Bot push ederken kullanıcı da
push edebilir; `commit-state` çakışmada botun sürümünü alıyor. **`posted.json`
istisna** — arşiv dosyası, iki taraftaki kayıtlar birleştiriliyor, yoksa
yayınlanmış haber tekrar aday olur.

**Windows'ta üretilen state Linux'ta okunuyor.** Yol yazarken `as_posix()`.
Betiklerin başında stdout/stderr utf-8'e çevriliyor (konsol cp1254).

**Bash heredoc kaçış karakterlerini bozuyor.** Python dosyalarına metin
yazarken düzenleme aracı kullanılmalı. YAML blok içinde de heredoc girintiyi
bozuyor — Python kodu ayrı dosyaya alınmalı.

**IGDB görsel boyutları uçurum gibi değişiyor** (600x338 ile 10681x7874 arası).
`MIN_IMAGE_WIDTH/HEIGHT` filtresi olmadan bulanık kart basılıyor. Kapak
metadata'sı küçük boyut raporluyor ama `t_original` büyüğünü veriyor.

**Satır içi stil enjekte edilen CSS'i ezer.** `--tier` değişkeni
`style.setProperty` ile basıldığı için stylesheet'ten değiştirilemiyor.

---

## 8. Ayarlanabilir eşikler

| Dosya | Sabit | Değer | Ne yapar |
|---|---|---|---|
| `fetch.py` | `CLUSTER_THRESHOLD` | 0.30 | IDF ağırlıklı başlık benzerliği |
| | `MIN_SHARED_IDF` | 3.0 | paylaşılan kelimelerin kanıt kütlesi |
| | `BRIDGE_DF` / `BRIDGE_THRESHOLD` | 2 / 0.15 | özel isim köprüsü |
| `tier.py` | `SOURCE_TIERS` | 4→S, 3→A, 2→B, 1→C | kademe tabanı |
| `images.py` | `NAME_MATCH_MIN` | 0.55 | oyun adı benzerliği |
| | `MIN_IMAGE_WIDTH/HEIGHT` | 1280x720 | çözünürlük tabanı |
| `write.py` | `MAX_ATTEMPTS` | 3 | üslup filtresi yeniden üretim |
| | `MIN_PAGES` / `MAX_PAGES` | 1 / 10 | post uzunluğu sınırı |
| `telegram.py` | `MAX_KUYRUK` | 3 | kuyrukta en fazla post |
| | `UYARI_SUSTURMA_DK` | 60 | aynı uyarı bu süre içinde bir kez |
| `render.py` | `SCALE` | 4/3 | 1080x1350 → 1440x1800 |

---

## 9. Sıradaki işler

Sıra **büyüme etkisine** göre.

**Bitti (2026-08-30):** esnek sayfa sayısı (bkz. bölüm 4). Canlıda
denenmedi: ilk `/uret`te görülecek.

⚠️ **Haftalık derleme İSTENMEDİ (2026-08-30).** Yazıldı, çalıştı, sonra
kullanıcı istemediğini söyledi ve tamamen geri alındı. Yeniden önerilmesin.
`state/weekly.json` da hiç oluşmuyor: `produce.py`'deki biriktirme kodu
duruyor ama menü akışı `--index` ile çağırdığı için o döngüye girilmiyor.

### Sistem değerlendirmesi (2026-08-30)
**Sağlam olan:** LLM'in dar tutulması, üslup filtresi, telif disiplini.

**Zayıf olan:**
- ⚠️ **Kademe sistemi fiilen ölü.** Üretilen postların hepsi B çıkıyor, S
  neredeyse hiç gelmiyor. Vitrindeki fikir çalışmıyor.
- Kaynak havuzu tek tip (22 RSS, hepsi İngilizce haber sitesi)
- Tam makale çekilmiyor, RSS özetleri birleştiriliyor — "duyuran" seviyede
- Görsel sayfa **tipine** göre dağıtılıyor, içerikle bağı tesadüf
- Tek format: hep haber. Uzunluk artık değişken ama format tek

**Büyüme tahmini:** Bu içerikle yavaş büyür ve sebebi kalite değil **format**.
Instagram kaydetme/paylaşma/yorumu ödüllendiriyor, haber ise tüketilip
geçiliyor. Kırılma ancak kaydedilebilir içerik eklenirse gelir.

⚠️ **Asıl risk teknik değil: ilginin sürekliliği.** Sistem her turda onay
bekliyor. Bir gün bakılmazsa post çıkmıyor. Çözüm ya koşullu otomatik onay ya
da tempoyu düşürmek (günde 3 yerine 1) — ikincisi daha sağlıklı.

### 1. Evergreen içerik
Haber 24 saatte ölüyor, evergreen aylarca erişim getiriyor ve kaydediliyor.
Altyapı hazır (aynı kart sistemi); değişecek olan içerik kaynağı — RSS değil
konu havuzu. Tier burada anlamsız, farklı bir görsel işaret gerekebilir.

### 2. Konu ısısı — kademe sistemini canlandırır
Sorun: sinyal "kaç kaynak aynı **başlığı** yazdı". GTA 6 tanıtımı gibi büyük
haberler dokuz ayrı kümeye bölünüyor, hiçbiri 3 kaynağa ulaşmıyor.

⚠️ **İki yaklaşım denendi, ikisi de başarısız — tekrar denenmesin:**
- *Union-find ile konu grubu:* zincirleme birleşti, 28 alakasız küme tek gruba düştü
- *Token sıcaklığı:* en sıcak kelimeler `shows, dev, version, tech, says`
  çıktı, hiçbiri konu değil

Sebep: istatistik "gta" ile "shows"u ayıramıyor, ikisi de nadir. Soru
**semantik**. Çalışacak yol: LLM'e sormak — ama tier'ı LLM'e teslim etmeden.
LLM veri verir ("bu haber hangi oyun hakkında"), ısıyı ve tier'ı kod hesaplar.
`menu.py` zaten oyun adı alıyor.

### 3. Profil ızgarasında tier şeridi
Bkz. bölüm 3'teki açık sorun.

### 4. Evergreen için kademe işareti
Evergreen içerikte kademe anlamsız (bölüm 9.1) ama kart bir kademe rengi
ve adı istiyor.

⚠️ Kolay görünen çözüm tuzaklı: `render.py`'de kademe adını ezmek kapak
kickerını düzeltir ama **son sayfadaki künyeyi de bozar** ("haberin
kademesi: ..."). İkisi `card.html` içinde aynı alandan (`data.tier_label`)
besleniyor. Ayırmak için şablona dokunmak gerekiyor - tasarım kararı.

### 5. Vision QA (`qa.py`)
Kod krem oranını ve çözünürlüğü zaten ölçüyor. LLM'in bakacağı: görsel konuya
uygun mu, kırpma tuhaf mı, yabancı logo var mı. Kota artık engel değil
(`HELPER_MODEL` 500/gün). Kurallar: rubrik ayrı dosyada, `temperature 0`,
sınırlı karar kümesi, en fazla 2 düzeltme turu.

### 6. Görsel-sayfa eşleştirme
LLM "3. sayfa savaş sisteminden bahsediyor, şu görsel ona uyar" diyebilir.

### Sonraya bırakılanlar
- **`watch.yml` · acil haber:** 10-15 dk'da bir `fetch.py`, ölçüt kaç kaynak
  değil **ne kadar sürede**. ⚠️ Konu ısısına bağımlı — o çalışmadan GTA 6
  tanıtımını bile yakalayamaz.
- **Twitter/X:** ücretsiz okuma yok (okuma başına ~$0.005). Kaynak değil
  **erken uyarı sensörü** olmalı: viral tweet doğrudan post olmaz, bot RSS'te
  doğrulama arar. `tier.py`'deki `community → C` kuralı bunu zaten söylüyor.
- **Steam yeni çıkanlar:** RSS'i yok, store API'siyle ayrı modül.
- **Otomatik onay:** koşullu (B + görsel var + QA temiz). Yukarıdaki "asıl
  risk" maddesiyle bağlantılı.

### Bilinen küçük borçlar
- Kademe adları hem `telegram.py` hem `render.py` içinde ayrı yazılı
- TR kaynaklar kapalı: karışık dilde "kaç kaynak yazmış" sinyali bozuluyordu
- Kaynak sayısı **yaygınlığı** ölçüyor, **ilginçliği** değil

---

## 10. Doğrulama komutları

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium

py -3.12 src/fetch.py --print
py -3.12 src/tier.py
py -3.12 src/render.py examples/sample_post.json --out out/deneme
py -3.12 src/menu.py --dry-run
py -3.12 src/apicheck.py --dry-run
py -3.12 src/publish.py state/drafts/<id>.json --cards out/<id> --dry-run
```
İlk üçü anahtarsız çalışır. `--dry-run` hiçbir yere göndermez.
