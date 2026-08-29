# quest.post

Türkçe indie/oyun haberleri paylaşan yarı otomatik Instagram içerik hattı.
Sunucu yok: her şey GitHub Actions üzerinde çalışacak.

Tasarım kararları, öğrenilen dersler ve yol haritası: **[DEVIR.md](DEVIR.md)**
Yeni bir sohbete geçerken önce onu oku.

## Kurulum

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium
```

Anahtarlar proje kökündeki `.env` dosyasında (git dışı):
`GEMINI_API_KEY`, `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET`,
`TG_BOT_TOKEN`, `TG_CHAT_ID`

## Kullanım

```bash
py -3.12 src/produce.py          # haber sec, metin yaz, kart bas, onaya sun
py -3.12 src/respond.py          # Telegram'daki karari uygula
```

Anahtarsız denenebilenler:

```bash
py -3.12 src/fetch.py --print                                     # haber toplama
py -3.12 src/tier.py                                              # kademe hesabi
py -3.12 src/render.py examples/sample_post.json --out out/deneme  # kart uretimi
```
