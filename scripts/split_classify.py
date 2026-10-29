"""分割線索判定（announcements.yml 用）。純函式，不連網，方便測試。

三層判定
  強   主旨本身含面額專屬字眼
  中   主旨沒有，但說明欄推得出「面額由 X 元變更為 Y 元」或寫明分割
  定向 公司已經在拆股流程中，主旨是股東會／章程／換股

2026-09-15 修正：「換股基準」移出強命中（減資換股公告被當成分割，4118/4155/6108/8176）。
2026-10-29 事故：長科 6548 的「公告本公司115年第三季合併自結損益(每股面額0.4元)」
  因主旨含「每股面額」被判成強命中「宣告拆股」。非 10 元面額的公司，財報、營收、
  自結損益公告的主旨都會附註「(每股面額X元)」，這只是說明現行面額，不是變更。
  改為：判定前先刪掉這類括號附註（只刪「每股面額＋單一金額」的括號，
  「面額由 10 元變更為 2.5 元」之類的真變更不受影響）。
"""
import re

# 第一層：面額專屬字眼。減資公告不會動到面額，所以這層不看否決字。
PAR_KW = ["股票分割", "股份分割", "面額分割", "股票面額", "每股面額",
          "面額變更", "變更面額", "票面金額"]
# 換股類字眼：只有已經在追蹤清單的公司才算數（第三層）
SWAP_KW = ["換發新股", "換股基準", "換股作業", "停止買賣", "最後交易日", "新股上市"]
# 否決字：主旨或說明碰到就丟掉（第一層的面額字眼優先，不受這裡影響）
VETO_KW = ["減資", "合併", "股份轉換", "股份交換", "認股權", "員工認股", "認股辦法",
           "限制員工權利新股", "轉換公司債", "可轉債", "私募",
           "現金增資", "盈餘轉增資", "資本公積轉增資", "庫藏股", "銷除", "註銷"]
TARGET_RE = re.compile(r"股東常會|股東臨時會|股東會|章程|換發新股|換股|停止買賣|新股上市|最後交易日")
PAR_PAIR = re.compile(
    r"面額.{0,12}?由\s*[「『\"]?\s*(?:新台幣)?\s*([\d.]+)\s*元?\s*[」』\"]?"
    r"\s*(?:調整|變更)為\s*[「『\"]?\s*(?:新台幣)?\s*([\d.]+)")
# 「(每股面額0.4元)」「（每股面額新台幣1元）」：現行面額附註，不是變更
PAR_NOTE = re.compile(r"[(（]\s*(?:普通股)?每股面額\s*(?:新台幣|NT\$)?\s*[\d.]+\s*元?\s*[)）]")


def strip_par_note(s):
    return PAR_NOTE.sub("", s or "")


def kind_of(subj):
    s = strip_par_note(subj)
    if re.search(r"換發新股|換股基準|停止買賣|最後交易日|新股上市", s): return "換股作業"
    if re.search(r"股東常會|股東臨時會|股東會", s):                    return "股東會"
    if re.search(r"章程", s):                                          return "章程變更"
    if re.search(r"董事會|決議|面額|分割", s):                          return "宣告拆股"
    return "其他"


def ratio_of(text):
    m = PAR_PAIR.search(text or "")
    if not m: return (None, None, None)
    try: a, b = float(m.group(1)), float(m.group(2))
    except ValueError: return (None, None, None)
    if a <= 0 or b <= 0: return (None, None, None)
    r = round(a / b) if a > b else None
    return (r if (r or 0) >= 2 else None, a, b)


def hit(kws, s):
    return next((k for k in kws if k in s), None)


def classify(a, watch=()):
    """a：{code, subject, detail}；watch：定向追蹤中的公司代號。回傳 (信心, 類別, 命中原因)。"""
    subj = strip_par_note(a.get("subject"))
    detail = strip_par_note(a.get("detail"))

    # 第一層：主旨帶面額專屬字眼 → 強
    k = hit(PAR_KW, subj)
    if k:
        return ("強", kind_of(subj), k)

    # 否決：主旨有這些字就到此為止
    if hit(VETO_KW, subj):
        return (None, None, None)

    # 第二層：說明欄推得出面額變更的數字對，或明寫分割
    if detail and not hit(VETO_KW, detail):
        r, _pa, _pb = ratio_of(subj + " " + detail)
        if r:
            return ("中", kind_of(subj), "說明推得出面額變更")
        if "面額" in detail and re.search(r"股票分割|股份分割|面額分割|拆股", detail):
            return ("中", kind_of(subj), "說明含分割")

    # 第三層：已知在拆股流程中的公司，主旨碰到節點關鍵字就算
    if a.get("code") in watch and (hit(SWAP_KW, subj) or TARGET_RE.search(subj)):
        return ("強", kind_of(subj), "定向追蹤")

    return (None, None, None)
