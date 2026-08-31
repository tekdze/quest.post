# DEVIR NOTU — quest.post

> Yeni sohbete geçerken **önce bunu oku.** Kararlar burada, kodda değil.
> Önemli bir karar alındığında burası güncellenir.

Son güncelleme: 2026-09-01 · **Sistem çalışıyor, gönderiler yayınlanıyor.**

**En son değişen** (bölüm 4.1 ve 9): metin kalitesi artık **yasakla değil
mekanizmayla** korunuyor — dayanak zorunluluğu, tekrar denetimi, olay
kategorileri · Reddit ilgi sinyali eklendi (`reddit.py`, anahtar bekliyor) ·
GitHub Models sondası hazır (`ghmodels.py`, çalıştırılmayı bekliyor).

**Ondan önce** (hepsi canlıda): kart tasarımı gradyansız bölme düzenine geçti
(bölüm 3) · görsel havuzu üç kaynaktan besleniyor (bölüm 4) · görsel-sayfa
eşleştirme ve kart denetimi eklendi (`qa.py`) · metin sesi değişti: "sen"
dili, evet/hayır sorusu yasak (bölüm 4) · üretim artık boş dönmüyor.

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
steam.py     Steam mağaza kareleri (havuzu tamamlar)
images.py    IGDB + Steam → seç, indir, kredi    → state/img/
qa.py        görsel-sayfa eşleştirme (görüntülü LLM, kod doğrular)
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

### Kart anatomisi — GRADYAN KALDIRILDI (2026-08-31)
- **Görsel kartın üstünü kaplayan ayrı bir bant**, metin altta krem blokta.
  Aradaki çizgi keskin, gradyan yok.
- Bölme çizgisi `card.html` içindeki `fitSplit()` ile metnin **ölçülen**
  boyuna göre kayıyor. Ölçülen görsel oranı: kapak %56-63 · metin %60-67 ·
  rakam %54 · son sayfa %53
- `object-position: 50% 50%` (eskiden %25'ti: yüzler gradyanın üstünde
  kalsın diyeydi, gradyan gidince gerekçe kalmadı ve gta kapağında logonun
  üstü kesiliyordu)
- Metin gölgesi/konturu **yok**, okunurluk krem blokla

**Neden değişti:** görsel tam kanamaydı ve üstüne krem gradyan biniyordu;
görüntü soluklaşıp "arka planda renk" gibi duruyordu. Üstelik 16:9 bir kare
4:5 karta sığmak için merkeze ağır yakınlaşıyor ve sahnenin yarısı
kayboluyordu (gta kapağında köy ve karakterler gidip gökyüzü kalıyordu).
Geniş bant, karenin kendi oranına yakın: hem daha çok görsel hem daha iyi
kadraj.

✔ **Oran onaylandı (2026-08-31).** Kapakta %56-63, metin sayfasında
%60-67. Başta %80 hedeflenmişti; kapakta kademe kutusu, tür kutusu,
başlık ve oyun adı satırının toplamı buna izin vermiyor. Kullanıcı bu
oranı yeterli buldu - yükseltmek için başlığı küçültmek ya da oyun adı
satırını kaldırmak gerekir, ikisi de istenmedi.

⚠️ **Sabit oran denendi, olmadı.** %80/%20 kapakta güzel duruyor ama metin
sayfasında başlığı görselin üstüne taşırıyor ve son maddeyi kesiyor.
Paragraf + 2 madde 270 piksele sığmıyor.

⚠️ **Taban SERT sınır değil.** Görsel oranının altına düşmemesi için taban
%52 konmuştu; 697px'lik bir metinde kart dışına taştı. Çizgi metnin bittiği
yere konur, yani metin her zaman sığar; taban %30'a indirildi ve orada
sadece "şerit gibi görsel" olmasını engelliyor. Kart görsel ağırlığını
metnin KISA olmasıyla korur, kırparak değil.
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
- Görseller **yalnızca resmi mağaza/veritabanı kaynaklarından**: IGDB ve
  **Steam** (karar 2026-08-31). İkisinde de materyali yayıncının kendisi
  yüklüyor, yani basın ve tanıtım için dağıtılan içerik.
  ⚠️ Google Görseller kaynak DEĞİL, indeks: oradaki karelerin sahipleri
  ayrı ayrı (ajanslar, YouTuber kayıtları, hayran çizimleri). İzinsiz
  kullanım ihlal; Instagram hak sahibi şikâyetiyle işlem yapıyor ve
  tekrarlayan uyarı hesabı kapattırabilir.
  ⚠️ **Epic ve itch.io denendi, alınmadı:** Epic'in herkese açık API'si
  yok (mağaza GraphQL'i belgesiz, her an kırılır); itch.io'nun API'si
  üreticinin kendi oyunları için, genel arama yok - kalanı kazıma olurdu.
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

### Oyun adı bulunamazsa — başlıktaki tırnak
Ölçüm (2026-08-31): menü "'Book Nook' has you creating tiny worlds"
haberi için `oyun: null` döndürdü (özet raf süslerinden bahsediyordu) ve
kullanıcıya **"görsel yok"** dedi. Oysa IGDB'de 14, Steam'de 11 görsel
vardı. Model kaçırdı, kod yakalıyor: `images.tirnakli_adlar` başlıktaki
tırnak içi adı çıkarıyor, hem `menu.py` hem `images.py` kullanıyor.

Aynı düzeltmeyle gelen iki şey:
- **IGDB hiç bulamazsa Steam tek başına** havuz kurabiliyor. Küçük indie
  oyunların çoğu IGDB'de yok ama Steam sayfası var; bu postlar eskiden
  doğrudan tipografiğe düşüyordu.
- **Kredi Steam'den tamamlanıyor.** IGDB'de şirket verisi olmayan
  oyunlarda kart kredisiz kalıyordu (Book Nook: 14 görsel var, stüdyo
  yok). Steam biliyor: `malapata studio`.

⚠️ **Menü üretimin GERÇEKTEN yapacağını göstermeli.** `gorsel_durumu`
yalnızca IGDB'ye bakıyordu; Steam ve haber görseli eklendiğinde menü
yanlış bilgi verir hale geldi. Kaynak eklerken menüyü de güncelle.

### Haberin kendi görselleri
Havuzdaki en ilgili kare, haberi yazan yayının o haber için seçtiği kare:
bir editör zaten "bu haberi hangi görsel anlatır" sorusunu cevaplamış.
Mağaza karesi ise pazarlama fotoğrafı, olayla bağı tesadüf ("köpek
poşetı" haberine arabadaki adam düşüyordu). `fetch.py` RSS'ten çekiyor
(`media_content`/`enclosure`), havuzun **başına** giriyorlar.

- Ölçüm (2026-08-31): İngilizce haber kaynaklarının **10/10**'u görsel
  veriyor, ama yalnızca **4**'ü 1280x720 eşiğini geçiyor (pcgamer, ign,
  polygon, pcgamesn). Gerisi 690-1166px küçültülmüş sürüm.
  ⚠️ `width=` parametresini büyütmek çözmüyor: gnwcdn'de kaynak asset
  zaten 1140px. Bulanık kart, ilgisiz görselden daha kötü görünüyor.
- **Kredi kaynağa yazılıyor** (`@polygon`), stüdyoya değil: kare o
  yayının haberinden geliyor ve bazen kendi kurgusu oluyor.

### Steam havuzu (`steam.py`)
IGDB tek kaynakken havuz bazı oyunlarda 3-4 kareye düşüyordu ve
eşleştirme ancak havuzdaki kadar iyi olabiliyor. Steam oyun başına
10-15 kare daha getiriyor (ölçüm: Silksong 13 -> 23 kare).

- Anahtar gerekmiyor: `SearchApps` ve `appdetails` herkese açık
- Kredi uydurulmuyor: `appdetails` geliştirici/yayıncı adı veriyor
- İsim eşiği ve sürüm kuralı IGDB ile **ortak** (`images.py`).
  ⚠️ Gerekli: "Grand Theft Auto VI" araması Steam'de "GTA V
  Enhanced" döndürüyor, kontrolsüz bırakılsa yanlış oyun basılırdı
- ⚠️ Steam boyut bilgisi VERMİYOR. Bulanık kart basmamak için ölçü
  şart, o yüzden dosyanın ilk 8 KB'ı çekilip JPEG/PNG başlığından
  boyut okunuyor (`goruntu_boyutu`, bağımlılık yok). Kareler
  1920x1080 çıkıyor: eşiğin üstünde ama IGDB'nin 4K artwork'lerinin
  altında, o yüzden havuzda IGDB önce sıralanıyor

### Kart denetimi (`qa.py --kartlar`)
Basılmış kartlar tek ızgarada modele gösteriliyor, **üç somut kusur**
soruluyor: `kirpik` (görselin içindeki yazı/tabela/logo kenarda yarım
kalmış), `okunmuyor`, `uygunsuz`. Kusurlu sayfaya kod havuzdan bir sonraki
kullanılmamış kareyi atıyor.

⚠️ **"Kırpık mı?" diye sorulmuyor, kesik yazı OKUTULUYOR.** Evet/hayır
sorusunda model "hayır"a meyilli. "Ne yazıyor?" sorusu doğrulanabilir:
okuyamıyorsa kesik yazı yoktur. Ölçüm: model `"jack of hea..."` ve
`"...auto"` diye okudu ve iki kartı işaretledi.

⚠️ **Gözlem-önce kuralı sessiz bir arızayı yakaladı.** İlk denemede model
"temiz" dedi ama gözlem alanı *"gri arka plan üzerinde sayılar var"*
diyordu: kartlar ızgaraya hiç yüklenmemişti. Chromium `set_content` ile
açılan sayfada `file://` alt kaynaklarını engelliyor - HTML dosyaya yazılıp
`goto` ile açılmalı. O alan olmasaydı "temiz" cevabı doğru sanılacaktı.

⚠️ Ölçüt yazarken KENAR belirtme: "üst kenarda kesik" dendiğinde sağ
kenardaki yarım tabelayı bildirmedi. Model kuralı doğru uyguluyordu,
kural eksikti.

### Görsel-sayfa eşleştirme (`qa.py`)
`images.py` kareyi sayfa **tipine** göre dağıtıyor; içerikle bağı
tesadüftü. Ölçüldü (20260830-gta-6): metin köpek gezdirmekten
bahsederken kartta arabadaki adam, sonraki sayfada arkada yarım kalmış
bir gece kulübü tabelası ve "adult entertainment" yazısı vardı.
Kartlar tek tek düzgündü ama post amatör duruyordu.

`qa.py` havuzu **tek numaralı ızgara** olarak modele gösteriyor
(`/havuz` çıktısının aynısı) ve her sayfa için numara istiyor. Post
başına **tek** görüntülü çağrı, kart başına değil.

İş bölümü değişmiyor - LLM veri verir, KOD uygular:
- sınırlı karar kümesi: yalnızca havuzdaki numaralar
- kod denetler: aralık, tekrar, ve **kapak ana oyundan mı**
  (model vitrin kuralını bilmiyor, uygulayan kod)
- reddedilen öneri sessizce düşer, o sayfa eski karesinde kalır

⚠️ **"İlgi çekici mi" diye SORULMUYOR, kıyaslatılıyor.** Mutlak
estetik yargısı güvenilir değil - model bozuk karta da "tamam" der,
serbest bırakılınca da her karede kusur bulur (bkz. tier ve menü
dersleri). Çarpıcılık, eşit derecede ilgili iki kare arasında
**ayırt edici ölçüt** olarak veriliyor, tek başına onay sorusu değil.

⚠️ **İyileştirme, zorunluluk değil.** `produce.py` bunu `run_yumusak`
ile çağırıyor: patlarsa post yine çıkar, sadece eşleştirme tip bazlı
kalır. Kota da engel değil, yardımcı modelde çalışıyor.

⚠️ **Sınır havuzun kendisi.** GTA 6 havuzunda köpek karesi yok; model
en az kötüyü seçebiliyor, olmayanı yaratamıyor. Asıl kazanç havuzu
büyütmekte (bkz. bölüm 9, Steam görselleri).

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

⚠️ **İşaretsiz Türkçe yeniden üretimle çözülmüyor, ONARIMLA çözülüyor.**
Yedek model (`flash-lite`) düzenli olarak "temali", "on incelemeler"
yazıyor; ham çıktıda ölçüldü, model özelliği. Yeniden üretim istemek
işe yaramıyordu - aynı hata tekrarlanıyor, üç deneme yanıyor ve ana
modelin kotası dolduğunda sistem fiilen duruyordu.

`write.diakritik_onar` metni yeniden yazdırmıyor, yalnızca işaretleri
geri koyduruyor (ucuz model, `temperature 0`). **Sonucu kod doğruluyor:**
dönen her metin, işaretler düşürüldüğünde orijinaliyle birebir aynı
olmak zorunda (`style.fold`). Kelime değişmişse o metin yok sayılır -
yani bu tur metni bozamaz, en kötü ihtimalle bir şey düzeltmez.
Ölçüm (2026-08-31): dün düşen haber yedek modelle üretildi, 13 metin
onarıldı, filtre temiz geçti.

### Ses ve hitap (2026-08-31)
Postlar "haber ajansı" gibi okunuyordu. Ölçülen kusurlar ve kod karşılıkları:

- **Son sayfa sorusu evet/hayır sorusuydu** ("ister miydiniz", "dener
  miydiniz"). Okurun söyleyecek bir şeyi kalmıyor, yorum gelmiyor.
  `EVET_HAYIR` soru ekine KİŞİ eki eklenmiş halleri yasaklıyor.
  ⚠️ Çıplak "mı/mi" yasak DEĞİL: "kötü olmak mı, sevimli olmak mı" iyi bir
  tercih sorusu ve aynı eki taşıyor.
- **`SORU_TIPLERI`**: tercih · karşıt görüş · kişisel deneyim · sebep ·
  somut ayrıntı. Her üretimde rastgele biri, `WRITING_MODES` gibi. Sabit
  bırakılınca model her postta aynı kalıbı yazıyordu.
- **"siz" dili yasak**, okura "sen" denir. Kartlar küçük harfli ve samimi;
  resmi çoğul dil tasarımla çelişiyordu. Denetim yalnızca okura seslenilen
  alanlarda (soru + çağrı) - gövdeye uygulansa filtre çok sıkı olurdu.
- **Gazeteci kelimeleri yasak**: "yapım" (oyuna oyun de), "söz konusu",
  "dikkat çekiyor", "imza attı", "hayata geçiriyor". "yapımcı" muaf.
- **Maddeler etiket değil cümle**: "detaylı dekorasyon seçenekleri" bir şey
  söylemiyor. Fiil işareti aranıyor (`yor/acak/abilir/mış`...).
  ⚠️ Kısa geçmiş zaman ekleri ("dı", "di") listede YOK: "kaydıyla" gibi
  isimlerde de geçip yanlış onay veriyorlardı.
- **İşaretsiz Türkçe kuralı yoğunluğa çevrildi.** Eskiden "hiç işaret yok"
  deniyordu ve tek bir "minyatür" kelimesi, gerisi tamamen işaretsiz 185
  karakterlik bir paragrafı geçirebiliyordu. Artık 45 karakterde en az bir
  işaret bekleniyor.

### Üretim artık boş dönmüyor (2026-08-31)
Filtre sıkılaştıkça iki üretim üst üste "3 denemede temiz çıktı alınamadı"
diye düştü ve **hiç post çıkmadı**. İki katman eklendi:

1. **Hedefli onarım** (`write.hedefli_onar`): bir ihlal yüzünden bütün postu
   çöpe atmak yerine sadece takılan alanları düzelttiriyor. İşaretsiz Türkçe
   onarımıyla aynı desen - LLM önerir, **kod doğrular**: onarılmış metin
   ancak ihlal SAYISINI düşürüyorsa kabul ediliyor, artırıyorsa eski metin
   kalıyor. Yani bu tur postu bozamaz.
2. **En az ihlalli taslak yayına aday.** Hiçbir deneme temiz çıkmazsa en az
   sorunlu olan yollanıyor ve Telegram özetinde "üslup filtresi N sorun
   buldu, düzeltilemedi" uyarısı çıkıyor. Kullanıcı kartlarda görüp karar
   veriyor; beğenmezse `/yeniden`. **Hiç post çıkmaması, kusurlu post
   çıkmasından kötü.**

⚠️ **Model şemayı atlayıp DİZİ döndürebiliyor.** Onarım turu
`{"metinler": [...]}` bekliyordu, model doğrudan `[...]` döndürdü ve üretim
`AttributeError: 'list' object has no attribute 'get'` ile düştü. Şema net
yazılsa bile oluyor. `write.liste_al` iki biçimi de kabul ediyor; menü, QA
ve eşleştirme çağrıları da aynı korumaya alındı.

⚠️ **Onarımda UZUNLUK EŞİT olmalı.** Metinler sıra bazlı değiştiriliyor
(`style.replace_strings`); eksik liste gelirse sıra kayar ve caption başlık
yerine oturur. Diakritik onarımında bunu `fold` karşılaştırması engelliyor
(kelime değişmişse reddediliyor) ama hedefli onarım serbestçe yeniden
yazdığı için içerik kıyaslanamıyor - tek koruma uzunluk denetimi.

⚠️ **Yedeğe geçiş "429" aramamalı.** Ana modelin günlük kotası dolunca
önce 429 geliyor, `api_call` tekrar deniyor ve SON hata 503 olabiliyor.
Koşul yalnızca "429" arayınca yedeğe geçmeden ölüyordu (ölçüm 2026-09-01,
`/uret 2`). Artık 429/500/502/503'ün hepsi yedeğe düşürüyor.

⚠️ **Hata mesajında SON satır işe yaramıyor.** Gemini hatası JSON gövdesiyle
geliyor ve son satır `}` - Telegram'a "write.py: }" düşüyordu.
`telegram.hata_satiri` yapısal satırları eliyor ve içinde
hata/error/message geçeni seçiyor; `produce.py` ve `respond.py` ortak
kullanıyor.

⚠️ **Kural eklerken ret olasılığı çarpılıyor.** Artık dört ret kaynağı var:
sayfa yapısı, üslup kalıpları, ses kuralları, LLM yazım denetimi. Üç hakla
üçünün de takılması artık ihmal edilebilir değil - yeni kural eklerken
mekanik düzeltme (autofix) ya da hedefli onarım tercih edilmeli.

⚠️ **İstem kural numaraları çakışmıştı.** Ses kuralları 11-16 olarak
eklenince eski 12-17 ile üst üste bindi ve modele iki tane "12. kural"
gidiyordu. Kural eklerken numaraları baştan sona kontrol et.

⚠️ **Kalan zayıf nokta:** çağrı kutusu hâlâ kalıba kaçıyor. "yorumlarda
paylaş" yasaklandı, model "aşağıda paylaşabilirsin" yazdı. Kutuyu posta
özel olmaya zorlamak ya da kaldırmak açık soru - kullanıcı kaldırmak
istemedi (takip daveti ayrı bir sabit satır, o kalıyor).

Yazım modu her üretimde rastgele seçiliyor (gözlem / karşılaştırma / tarihsel
not / sayısal detay / karşı görüş) — sabit açılış kalıbı oluşmasın.

⚠️ **Karta basılmayan alanlar `NON_PROSE_KEYS`'e girmeli.** `search_name`,
`image_candidates`, `series_fallback`, `representative_games`, `studio`
İngilizce oyun adları ve
büyük harf içermek zorundalar. Denetime girdiklerinde filtre LLM'i o alanları
**boşaltmaya itiyor** ve arıza hata olarak değil *eksik özellik* olarak
görünüyor.

---

## 4.1 Kalite mekanizmaları (2026-09-01) — YASAK DEĞİL MEKANİZMA

**Teşhis.** İstemde 22 kural vardı ve **hepsi yasaktı.** Hiçbiri "iyi post
şudur" demiyordu. 22 yasağa göre optimize edilen model en güvenli metni
yazar ve **en güvenli metin en boş metindir** — hiçbir şey söylemeyen cümle
hiçbir kuralı ihlal edemez.

Ölçüm (20260831-the-blood-of-dawnwalker): *"sıradan gözüken arayışlar
oyuncuyu hızlıca karanlık atmosfere çekiyor"* maddesi 22 kuralın 22'sini de
geçti. Oysa kaynakta yerini alacak somut bir anekdot vardı (turba kazıcısı
çukura düşüyor, mağarada bir ses duyuluyor) ve model onu **soyutlayıp attı.**

⚠️ Bu bir GİRDİ sorunu değildi. Anekdot RSS özetinde tam olarak vardı ve
`source_text_of` onu modele verdi. Yani "tam makale çekilmiyor" maddesi bu
postta geçerli değil — eksik bilgi değil, **eksik yargı** vardı. İkisi
tamamen farklı sorunlar ve farklı çözümleri var.

⚠️ **Yasak eklemenin marjinal getirisi artık negatif.** Yeni kural hem ret
olasılığını çarpıyor hem metni daha da ortalamaya itiyor. Bundan sonraki
düzeltmeler kural değil mekanizma olmalı.

### 1. Dayanak zorunluluğu (`check_dayanak`, `autofix_dayanak`)

Model önce `cikarim` listesini yazıyor — **şemada ilk sırada**, yani metnini
kendi çıkarımına koşullanarak yazıyor. Her olgu için kaynaktan **birebir
alıntı** veriyor, sonra her paragraf ve her madde o listeden bir numara
gösteriyor.

- Kod alıntıyı doğruluyor (kelimelerin %70'i kaynakta geçmeli). Uydurulmuş
  olgu düşer. Diakritik onarımındaki `fold` karşılaştırmasıyla aynı desen:
  **LLM veri verir, kod doğrular.**
- **Numara tekrar edilemez.** Yan etkisi tasarım gereği: kaynakta 5 olgu
  varsa post 5 gövde alanından uzun olamaz. Yani sayfa sayısı artık modelin
  tahminine değil **kaynağın yoğunluğuna** bağlı ve dolgu sayfa yapısal
  olarak imkânsız.
- Tam eşleşme değil %70 aranıyor: model tırnak ve boşlukları sessizce
  düzeltiyor, tam eşleşme şartı ret oranını gereksiz şişiriyordu.

⚠️ **"En az 4 olgu" kuralı DENENDİ ve GERİ ALINDI.** Üretim üç denemenin
üçünde de takıldı, çünkü `hedefli_onar` metin yazar — **listeye olgu
ekleyemez.** Onarılamayan bir ihlal her seferinde bir deneme yakıyor.
Ders: *onarılamayan kural eklenmez.* Ayrıca eşik yanlış kaldıraçtı — model
3 olgu çıkarıp 3 gövde alanı yazdıysa post kısa ama dürüst.

⚠️ **Ret oranı DÜŞTÜ, artmadı.** İhlallerin çoğu mekanik olarak onarılıyor
(`autofix_dayanak`): tekrar eden madde siliniyor, dayanaksız madde
kesiliyor, gövdesi tekrar olan sayfa düşüyor. Ölçüm: üç arka arkaya koşunun
üçü de **birinci denemede** temiz çıktı (yedek modelle).

⚠️ `dayanak` ve `bullet_dayanak` **`NON_PROSE_KEYS`'e girmek zorundaydı.**
Model bu alanlara sayı yerine metin yazdığında üslup filtresi o alanlara
saldırıyordu ("işaretsiz Türkçe", "eğik tırnak") — `search_name` dersinin
birebir tekrarı: doğrulama mekanizmasının kendisi filtreye yem oluyordu.

### 2. Tekrar denetimi (`style.check_tekrar`) — deterministik

Mevcut denetimlerin hepsi **tek metne** bakıyordu, hiçbiri metinler
**arasına** bakmıyordu. Dawnwalker'da "karanlık" 4, "fikir" 3 ayrı alanda
geçti ve hiçbir kural ihlal edilmedi.

Türkçe eklemeli olduğu için tam eşleşme işe yaramaz: kaba kök olarak ilk
5 harf alınıyor ("karanlık/karanlığa" → `karan`, "fikirlerini" → `fikir`).
4 harf çok kaba: "karanlık" ile "karakter" çakışıyordu.

⚠️ **Yalnızca GÖVDEYE bakıyor** (paragraf + maddeler). Ölçüm: başlık ve son
sayfa sorusu dahil edilince 11 taslağın 11'i de işaretlendi, yani filtre
hiçbir şey ayırt etmiyordu. Konu kelimesinin kapakta, bir paragrafta ve
soruda geçmesi tekrar değil tutarlılıktır. Gövdeye daraltılınca 11 taslakta
4 işaret kaldı ve en çok da en tekrarlı post işaretlendi. `credit` de
dışarıda: sayfa başına yazılan aynı stüdyo adı tekrar değil.

### 3. Kategoriler artık OLAY tipi

Eski listede `stüdyo` vardı ve o bir olay değil bir **özne**. Ölçüm:
Dawnwalker üç yayının **incelemesiydi** ama listede "inceleme" yoktu, model
mecburen "stüdyo" seçti ve kapak kutusu haberi yanlış bildirdi. **Kusur
modelde değil, sözlükte eksiklikti.**

Eklenenler: `inceleme`, `duyuru`, `fragman`, `gecikme`. Ayrıca her
kategorinin **zorunlu bilgisi** isteme yazıldı (`KATEGORI_SLOTLARI`) —
inceleme postunda "kaynaklar oyunu nasıl buldu" yoksa post haberi hiç
vermemiş olur.

⚠️ Bu, kapak başlığı tartışmasının da çözümü. "witcher ekibinden vampir
rpg'si" başlığı **iyi bir başlık** (tür vaadi net, çengel güçlü) ama fiil
taşımıyor: aynı cümle duyuruya da, fragmana da, ertelemeye de uyar. Başlığı
zorlamak yerine **olay kategori kutusuna** bırakıldı; ikisi birlikte hem
çengeli hem haberi veriyor.

### Ölçülen sonuç (aynı haber, aynı kaynak)

| | eski | yeni |
|---|---|---|
| kategori | stüdyo (yanlış) | inceleme |
| incelemelerin yargısı | **yok** | eurogamer ve pc gamer karşı karşıya |
| turba kazıcısı anekdotu | soyutlanıp atılmış | kendi sayfasında |
| tekrar | "karanlık" ×4, "fikir" ×3 | yok |
| dolgu madde | 2 | yok |
| metin sayfalarında görsel oranı | %60-67 | **%71-77** |
| deneme sayısı | - | 1 (sıfır ihlal) |

⚠️ Metin kısaldığı için görsel oranı kendiliğinden yükseldi — bölüm 3'te
"%80 hedeflenmişti, başlık ve kutular izin vermiyor" deniyordu. Kapakta hâlâ
geçerli ama metin sayfalarında sınır **metnin uzunluğuydu** ve o sınır
kalktı.

⚠️ **Kalan zayıf nokta: caption dayanaksız.** Gövde artık kaynağa bağlı ama
caption bağlı değil ve ölçümde kaynakta olmayan bir iddiaya kaydı
("eleştirmenlerden farklı tepkiler aldı" — üç kaynak da olumluydu).
`#indiegame` etiketi de hâlâ yanlış basılıyor.

---

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
  style.py      üslup filtresi + tekrar denetimi
  reddit.py     ilgi sinyali (anahtar yoksa sessizce kapalı)
  ghmodels.py   GitHub Models sondası (entegrasyon DEĞİL)
  steam.py      Steam mağaza görselleri
  images.py     IGDB + Steam görsel seçimi
  qa.py         görsel-sayfa eşleştirme
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

**Bekleyen (ikisi de opsiyonel, yokken sistem eskisi gibi çalışır):**
`REDDIT_CLIENT_ID` · `REDDIT_CLIENT_SECRET` — ilgi sinyali için.
reddit.com/prefs/apps → "script" tipi uygulama → ücretsiz, salt okuma.
`GH_MODELS_TOKEN` yalnızca yerel deneme için; Actions'ta `GITHUB_TOKEN`
zaten var ve `permissions: models: read` yeterli.

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

**Bitti (2026-09-01 akşamı):** dayanak zorunluluğu · tekrar denetimi · olay
kategorileri (bölüm 4.1) · Reddit sinyali yazıldı (anahtar bekliyor) ·
GitHub Models sondası yazıldı (çalıştırılmayı bekliyor).

**Bitti (2026-08-30/09-01):** esnek sayfa sayısı · sızıntı postlarında
görsel · görsel-sayfa eşleştirme ve kart denetimi (`qa.py`) · Steam havuzu
(`steam.py`) · haberin kendi görselleri · işaretsiz Türkçe onarımı · ses
kuralları · gradyansız kart tasarımı · üretim dayanıklılığı (hedefli onarım,
en az ihlalli taslak, yedek modele geçiş, hata sebebinin taşınması).

⚠️ **Haftalık derleme İSTENMEDİ (2026-08-30).** Yazıldı, çalıştı, sonra
kullanıcı istemediğini söyledi ve tamamen geri alındı. Yeniden önerilmesin.
`state/weekly.json` da hiç oluşmuyor: `produce.py`'deki biriktirme kodu
duruyor ama menü akışı `--index` ile çağırdığı için o döngüye girilmiyor.

### Sistem değerlendirmesi (2026-08-30)
**Sağlam olan:** LLM'in dar tutulması, üslup filtresi, telif disiplini.

**Zayıf olan (2026-09-01 akşamı itibarıyla):**
- ⚠️ **Seçim ölçütü yaygınlık, ilginçlik değil.** "Kaç kaynak yazdı" en çok
  tekrarlanan, yani en sıradan haberi öne çıkarıyor. **Reddit sinyali bunun
  için yazıldı** (`reddit.py`) ama anahtar bekliyor — girilene kadar açık
  devam ediyor.
- ⚠️ **Kademe sisteminde ölçüm güncellendi.** "Hepsi B çıkıyor" gözlemi artık
  doğru değil: Dawnwalker A çıktı. Ayrıca kullanıcı bu tier'ı **onayladı** —
  yeni bir oyunun incelemesi oyuncu için gerçekten heyecan verici, "sıradan"
  olan basının rutini, okurun ilgisi değil. Yani sorun tier'ın **kendisinde
  değil**, hesabın tek sinyale dayanmasında.
- Kaynak havuzu tek tip (RSS, hepsi haber sitesi)
- Tam makale çekilmiyor, RSS özetleri birleştiriliyor
  ⚠️ Ama bu maddenin ağırlığı DÜŞTÜ: Dawnwalker ölçümünde kaçan anekdot
  RSS özetinde zaten vardı. Kayıp bilgide değil işlemedeydi ve bölüm 4.1
  onu çözdü. Tam makale hâlâ değerli, ama artık birinci sırada değil.
- Tek format: hep haber. Uzunluk ve ses değişti ama format tek
- Görsel-içerik bağı DÜZELDİ (`qa.py` eşleştirme + kart denetimi)
- Metin dolgusu DÜZELDİ (bölüm 4.1)

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
**semantik**.

✔ **Çözüm yazıldı: Reddit oyu** (`reddit.py`). Semantik soruyu istatistikle
çözmeye çalışmak yerine, insanların zaten cevapladığı yerden okuyoruz. Oy
sayısı ilginçliğin doğrudan ölçüsü ve kaynak sayısından bağımsız.
Sinyal yalnızca **yukarı** itiyor (bölüm 6'daki gerekçe), yorum/oy oranı
yüksekse ayrıca yükseltiyor — Instagram'da yorum en değerli etkileşim.
**Anahtar girilene kadar etkisiz.**

### 3. Profil ızgarasında tier şeridi
Bkz. bölüm 3'teki açık sorun.

### 4. Evergreen için kademe işareti
Evergreen içerikte kademe anlamsız (bölüm 9.1) ama kart bir kademe rengi
ve adı istiyor.

⚠️ Kolay görünen çözüm tuzaklı: `render.py`'de kademe adını ezmek kapak
kickerını düzeltir ama **son sayfadaki künyeyi de bozar** ("haberin
kademesi: ..."). İkisi `card.html` içinde aynı alandan (`data.tier_label`)
besleniyor. Ayırmak için şablona dokunmak gerekiyor - tasarım kararı.

### 5. Kart denetimi — kırpma ve okunurluk
`qa.py` şu an eşleştirme yapıyor, basılmış kartı denetlemiyor. Sıradaki:
render edilmiş kartı modele gösterip yalnızca üç şeyi sormak - görselin
içindeki yazı kadrajda yarım mı kaldı, kart metni zemin yüzünden
okunmuyor mu, uygunsuz bir öge var mı. Kurallar aynı: rubrik ayrı
dosyada, `temperature 0`, sınırlı karar kümesi, en fazla 2 düzeltme turu.

### Sıraya alındı — kullanıcı onayladı, sonra yapılacak

**A. Yeni sayfa tipleri: karşılaştırma, zaman çizelgesi, alıntı kartı.**
Şu an dört karttan üçü aynı kalıp: başlık + paragraf + iki madde. Kaydedilen
carousel'ler genelde paragraf değil **yapı** taşır. Gerekçe bölüm 4.1'deki
mekanizmayla aynı yönde: **yapı boş cümle taşıyamaz** — karşılaştırma
tablosu doldurmak için gerçek iki taraf gerekir, dolgu cümle o yapıya
sığmaz. Metin kalitesini istemle kovalamaktan daha çok iş görür ve bu bir
**tasarım** kararı, model kararı değil.

**B. Eval seti — post birikince.** 12-15 dondurulmuş aday, her istem
değişikliğinden sonra hepsi yeniden üretilip puanlanır (deterministik
metrikler + sabit rubrik). "Bu postta sınırı düzeltiyorsun, başka postta
bozuluyor" probleminin tek çözümü bu; şu an yapılmadı çünkü tasarım yeni ve
elde yeterli post yok. **Bu kurulmadan yapılan her iyileştirme yazı tura.**

**C. Evergreen içerik.** Aşağıdaki 9.1 maddesi. Kullanıcı sonraya bıraktı.

**D. `/keskinlest` komutu.** Beğenilen bir habere elle "güçlü modelle,
eleştiri turuyla yeniden yaz" diyebilmek. Zemin makinenin işi, tavan
kullanıcının: her posta güçlü model harcamak yerine hangisinin buna
değdiğine kullanıcı karar verir.

**E. Ders dosyası (`dersler.json`).** İstem şu an 22 yasak taşıyor ve yasak
eklemenin getirisi negatif (bölüm 4.1). Bunun yerine somut örnekler
biriktirilir (`kötü / iyi / sebep`) ve her üretimde tipine uygun 3 tanesi
örneklenir. Örnekler yasak gibi birikmiyor — 40 örneğin 3'ü kullanılır,
istem uzamaz. Beslemesi: `/not <serbest metin>` komutu; kullanıcı doğal
konuşur, yapılandırmayı ucuz model yapar. **Sabit soru-cevap anketi
İSTENMEDİ** — kullanıcı agent ile konuşmak istiyor, form doldurmak değil.

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
