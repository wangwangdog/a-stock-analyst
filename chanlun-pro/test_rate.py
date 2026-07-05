import os, time, sqlite3, json, urllib.request
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
c = sqlite3.connect(DB, timeout=30)
stale = [r[0] for r in c.execute(
    "SELECT symbol FROM kline_cache WHERE period='5m' "
    "GROUP BY symbol HAVING MAX(trade_date) < '2026-06-02' LIMIT 200"
).fetchall()]
c.close()
print(f"test {len(stale)} stocks", flush=True)

t0 = time.time()
ok = fail = 0
for s in stale:
    pref = "sh" if s.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{s},m5,,320"
    try:
        r = urllib.request.urlopen(url, timeout=5)
        data = json.loads(r.read())
        klines = data.get("data", {}).get(f"{pref}{s}", {}).get("m5", [])
        if klines and isinstance(klines, list):
            ok += 1
        else:
            fail += 1
    except:
        fail += 1
    if (ok+fail) % 20 == 0:
        el = time.time()-t0
        print(f"  {ok+fail} ok:{ok} fail:{fail} {el:.1f}s", flush=True)
print(f"done ok:{ok} fail:{fail} {time.time()-t0:.1f}s", flush=True)
