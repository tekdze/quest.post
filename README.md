# quest.post

Türkçe oyun haberleri paylaşan yarı otomatik Instagram içerik hattı.
Sunucu yok: her şey GitHub Actions üzerinde çalışıyor.

Kararlar, tasarım kuralları ve yol haritası: **[DEVIR.md](DEVIR.md)**
Yeni bir sohbete geçerken önce onu oku.

## Nasıl çalışıyor

Günde üç kez Telegram'a aday haber menüsü düşer. Seçtiğin haber için metin
yazılır, IGDB'den görsel seçilir, kartlar basılır ve onayına sunulur.
Onaylarsan Instagram'a carousel gönderi olarak yayınlanır.

```
/konular      günün adaylarını listele
/uret 2       seçileni üret
/ok           onayla ve paylaş
/komutlar     tüm komutlar
```

## Kurulum

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium
```

Anahtarlar proje kökündeki `.env` dosyasında (git dışı) ve GitHub Secrets'ta:
`GEMINI_API_KEY` · `IGDB_CLIENT_ID` · `IGDB_CLIENT_SECRET` ·
`TG_BOT_TOKEN` · `TG_CHAT_ID` · `IG_ACCESS_TOKEN` · `IG_USER_ID`

## Elle çalıştırma

```bash
py -3.12 src/menu.py              # aday menüsü üret ve yolla
py -3.12 src/produce.py --index 1 # doğrudan üret (menüyü atlayarak)
py -3.12 src/respond.py           # Telegram'daki komutları uygula
py -3.12 src/apicheck.py          # anahtarların durumu
```

Anahtarsız denenebilenler:

```bash
py -3.12 src/fetch.py --print
py -3.12 src/tier.py
py -3.12 src/render.py examples/sample_post.json --out out/deneme
```
