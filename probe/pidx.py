import re, sys, json, subprocess
sys.path.insert(0, "scripts")
from cash_issue import _get, _op
import urllib.request
def raw(u):
    with _op.open(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=40) as r:
        return r.read()
pdf = raw("https://www.twse.com.tw/news/news/tsecnews/8a8216d69fc76da0019ffa56a07f0104.pdf")
open("/tmp/m.pdf", "wb").write(pdf); print("pdf bytes", len(pdf))
print(subprocess.run(["pdftotext", "-layout", "/tmp/m.pdf", "-"], capture_output=True, text=True).stdout[:4000])
s = _get("https://www.taiwanindex.com.tw/news")
print(sorted(set(re.findall(r'["\'](https?://[^"\']*api[^"\']*|/api/[^"\']+)["\']', s)))[:30])
for js in sorted(set(re.findall(r'src="([^"]+\.js)"', s)))[:8]:
    u = js if js.startswith("http") else "https://www.taiwanindex.com.tw" + js
    try:
        t = _get(u)
        print(js, sorted(set(re.findall(r'["`\'](/api/[^"`\']+|https://[^"`\']*api[^"`\']*)["`\']', t)))[:20])
    except Exception as e: print(js, e)
