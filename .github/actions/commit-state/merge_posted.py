#!/usr/bin/env python3
"""Rebase çakışmasında posted.json'u birleştirir.

Diğer state dosyalarında "en son yazan geçerli" doğru davranış, ama
posted.json yayınlanan ve iptal edilen haberlerin arşivi ve ekleme yapılan
bir dosya. Bir tarafın sürümünü almak, diğer taraftaki kayıtların
kaybolması ve o haberlerin tekrar aday olarak gelmesi demek.

Git aşama numaraları: 2 = uzaktaki (upstream), 3 = uygulanan commit (bot).
"""
import json
import subprocess
import sys


def oku(asama: int) -> list[dict]:
    try:
        ham = subprocess.run(["git", "show", f":{asama}:state/posted.json"],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(ham).get("posted", [])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


birlesik: list[dict] = []
gorulen: set[str] = set()
for row in oku(2) + oku(3):
    h = row.get("hash")
    if h and h not in gorulen:
        gorulen.add(h)
        birlesik.append(row)

if not birlesik:
    print("posted.json birlestirilemedi, iki taraf da bos okundu", file=sys.stderr)
    raise SystemExit(1)

with open("state/posted.json", "w", encoding="utf-8") as f:
    json.dump({"posted": birlesik}, f, ensure_ascii=False, indent=2)
print(f"posted.json birlestirildi: {len(birlesik)} kayit")
