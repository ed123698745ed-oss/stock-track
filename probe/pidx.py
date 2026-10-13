import re, sys, json
sys.path.insert(0, "scripts")
from cash_issue import _get, _text
s = _get("https://www.taiwanindex.com.tw/news")
for m in re.finditer(r"臺灣50|台灣50|MSCI|成分股", s):
    print("TI ...", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s[max(0, m.start()-200):m.end()+200]))[:400])
    break
links = re.findall(r'href="(/news/[^"]+)"', s); print("TI links", links[:15])
for p in range(1, 40):
    try:
        j = json.loads(_get(f"https://www.twse.com.tw/rwd/zh/news/newsList?response=json&page={p}"))
    except Exception as e:
        print("page", p, e); break
    for r in j.get("data", []):
        if re.search(r"臺灣50|台灣50|成分股|MSCI", r[1]):
            print("TWSE", p, r)
    if not j.get("data"): break
