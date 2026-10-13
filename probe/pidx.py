import re, sys, json
sys.path.insert(0, "scripts")
from cash_issue import _get, _text
def show(u, n=1500, hdr=None):
    try:
        s = _get(u, hdr=hdr); print("==", u, len(s)); return s
    except Exception as e:
        print("==", u, "ERR", e); return ""
s = show("https://www.taiwanindex.com.tw/news")
for m in re.findall(r'href="([^"]*news[^"]*)"[^>]*>([^<]{4,80})<', s)[:40]: print("  ", m)
for u in ["https://www.taiwanindex.com.tw/api/news?page=1", "https://www.taiwanindex.com.tw/api/News/GetNewsList",
          "https://www.taiwanindex.com.tw/indexes/0050"]:
    t = show(u); print(_text(t)[:800])
s = show("https://www.msci.com/index-review")
print(_text(s)[:1500])
for m in re.findall(r'href="([^"]+\.(?:pdf|xlsx?))"', s)[:20]: print("  link", m)
s = show("https://www.msci.com/our-solutions/indexes/index-review")
print(_text(s)[:800])
# TWSE 新聞（0050 成分股調整也會公告）
s = show("https://www.twse.com.tw/rwd/zh/news/newsList?response=json")
print(s[:1500])
