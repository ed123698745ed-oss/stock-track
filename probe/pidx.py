import re, sys, json
sys.path.insert(0, "scripts")
from cash_issue import _get, _text
i1, i2 = "8a8216d69fc76da0019ffa56a0a00105", "8a8216d69fc76da0019ffa56f32b0107"
for u in [f"https://www.twse.com.tw/rwd/zh/news/newsDetail?id={i1}&response=json",
          f"https://www.twse.com.tw/rwd/zh/news/newsDetail?id={i2}&response=json",
          f"https://www.twse.com.tw/rwd/zh/news/content?id={i1}&response=json",
          f"https://www.twse.com.tw/zh/about/news/news/content.html?{i1}",
          f"https://www.twse.com.tw/zh/news/newsDetail?id={i1}"]:
    try:
        s = _get(u); print("==", u, len(s)); print(_text(s)[:2500])
    except Exception as e: print("==", u, "ERR", e)
s = _get("https://www.taiwanindex.com.tw/news")
t = _text(s)
for m in re.finditer(r"臺灣50|台灣50|成分股", t):
    print("TI ...", t[max(0, m.start()-150):m.end()+150]); 
links = sorted(set(re.findall(r'href="([^"]+)"', s))); print([l for l in links if "news" in l][:40])
