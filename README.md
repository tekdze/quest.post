# quest.post

Türkçe indie/oyun haberleri paylaşan yarı otomatik Instagram içerik hattı.
Sunucu yok: her şey GitHub Actions üzerinde çalışır.

Tasarım kararları ve yol haritası: **[DEVIR.md](DEVIR.md)** — önce onu oku.

## Kurulum (yerel geliştirme)

```bash
py -3.12 -m pip install -r requirements.txt
```

## Faz 1 — haber toplama (anahtar gerekmez)

```bash
py -3.12 src/fetch.py --print
```

RSS kaynaklarını tarar, aynı haberi yazan kaynakları kümeler,
`state/candidates.json` dosyasına aday listesi yazar.
