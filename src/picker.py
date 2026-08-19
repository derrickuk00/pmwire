"""選題引擎：由上千個市場揀出今次最值得寫嘅一個。

核心原則：唔係「賠率報時」，係「偵測異動」。
一個市場值得寫，係因為佢郁咗、而且有人真金白銀喺度郁 —— 唔係因為佢存在。
"""
from __future__ import annotations
import math
import datetime as dt
from common import log, load_posted, parse_iso, utcnow
from deadline import family_key


def _days_to_end(m: dict) -> float | None:
    end = parse_iso(m.get("end_date"))
    if end is None:
        return None
    return (end - utcnow()).total_seconds() / 86400.0


def hard_filter(markets: list[dict], cfg: dict) -> list[dict]:
    """硬性門檻。過唔到就唔考慮，唔會出現喺評分階段。"""
    s = cfg["selection"]
    kept, reasons = [], {}

    def drop(key):
        reasons[key] = reasons.get(key, 0) + 1

    blocked = set(s.get("blocked_categories") or [])
    allowed = set(s.get("allowed_categories") or [])
    lo, hi = s.get("min_price", 0.0), s.get("max_price", 1.0)

    vol_by_cat = s.get("min_volume_by_category") or {}

    for m in markets:
        cat = m.get("category", "other")
        if cat in blocked:
            drop(f"主題排除({cat})"); continue
        if allowed and cat not in allowed:
            drop(f"主題唔喺白名單({cat})"); continue
        if s.get("exclude_price_ladders", True) and m.get("price_ladder"):
            drop("價格階梯市場"); continue
        if not (lo <= m["yes_price"] <= hi):
            drop("賠率太接近定局"); continue
        # 分類別成交額門檻：政治／地緣盤本身細，唔可以用同一把尺
        min_vol = vol_by_cat.get(cat, s["min_volume_24hr"])
        if m["volume_24hr"] < min_vol:
            drop("成交額太低"); continue
        if m["liquidity"] < s["min_liquidity"]:
            drop("流動性太淺"); continue
        if abs(m["move_24h"]) < s["min_abs_move_24hr"] and \
           abs(m["move_1h"]) < s["min_abs_move_24hr"]:
            drop("冇郁過"); continue
        d = _days_to_end(m)
        if d is None:
            drop("冇到期日"); continue
        if d < s["min_days_to_resolution"]:
            drop("太快到期"); continue
        if d > s["max_days_to_resolution"]:
            drop("太遠期"); continue
        m["days_to_end"] = d
        kept.append(m)

    log(f"硬性過濾：{len(markets)} → {len(kept)}　" +
        "　".join(f"{k}×{v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    return kept


def cooldown_filter(markets: list[dict], cfg: dict, posted: dict) -> list[dict]:
    """冷卻期：出過嘅市場短期內唔再出，除非佢郁得好勁。

    呢個就係『1500 篇唔會大量重複』嘅機制。
    """
    s = cfg["selection"]
    cd = dt.timedelta(days=s["cooldown_days"])
    now = utcnow()
    kept, blocked, overridden = [], 0, 0

    for m in markets:
        rec = posted.get(m["condition_id"])
        if not rec:
            kept.append(m); continue
        last = parse_iso(rec.get("last_posted"))
        if last is None or (now - last) > cd:
            kept.append(m); continue
        # 仲喺冷卻期內 —— 除非異動大到必須講
        if max(abs(m["move_1h"]), abs(m["move_24h"])) >= s["cooldown_override_move"]:
            m["_cooldown_override"] = True
            overridden += 1
            kept.append(m)
        else:
            blocked += 1

    log(f"冷卻期：擋咗 {blocked} 個，因大異動放行 {overridden} 個，剩 {len(kept)}")
    return kept


def diversity_filter(markets: list[dict], cfg: dict, posted: dict) -> list[dict]:
    """多樣性配額：類別配額 + 家族配額。

    ⚠️ 家族配額係 2026-08-19 實測加嘅。當日頭 10 名有 6 個
       都係伊朗／荷姆茲同一件事，其中三個係同一條問題唔同 deadline
       （"ceasefire continues through Aug 31 / Sept 30 / …"）。
       冇呢層去重，你會連續出幾篇幾乎一樣嘅嘢。

       家族用 deadline.family_key() 判斷 —— 剪走日期之後文字一樣
       就當同一家族。呢個函數本身係為階梯掃描而寫，啱好用得著。
    """
    s = cfg["selection"]
    now = utcnow()
    day = dt.timedelta(hours=24)

    cat_count: dict[str, int] = {}
    fam_count: dict[str, int] = {}
    for rec in posted.values():
        last = parse_iso(rec.get("last_posted"))
        if last and (now - last) < day:
            c = rec.get("category", "other")
            cat_count[c] = cat_count.get(c, 0) + 1
            f = rec.get("family", "")
            if f:
                fam_count[f] = fam_count.get(f, 0) + 1

    full_cats = {c for c, n in cat_count.items() if n >= s["max_per_category_24h"]}
    if full_cats:
        log(f"類別配額已滿（24h 內）：{', '.join(sorted(full_cats))}")

    subj_count: dict[str, int] = {}
    for rec in posted.values():
        last = parse_iso(rec.get("last_posted"))
        if last and (now - last) < day:
            sj = rec.get("subject", "")
            if sj:
                subj_count[sj] = subj_count.get(sj, 0) + 1

    max_fam = s.get("max_per_event_24h", 2)
    max_subj = s.get("max_per_subject_24h", 3)
    kept: list[dict] = []
    seen_fam: dict[str, int] = dict(fam_count)
    seen_subj: dict[str, int] = dict(subj_count)
    dropped_fam = dropped_subj = 0

    for m in markets:
        if m["category"] in full_cats:
            continue
        fam = family_key(m["question"]) or m["question"].lower()[:60]
        m["_family"] = fam
        if seen_fam.get(fam, 0) >= max_fam:
            dropped_fam += 1
            continue
        # 主體配額：同一件真實世界嘅事唔好一日出七篇
        sj = m.get("subject", "")
        if sj and seen_subj.get(sj, 0) >= max_subj:
            dropped_subj += 1
            continue
        seen_fam[fam] = seen_fam.get(fam, 0) + 1
        if sj:
            seen_subj[sj] = seen_subj.get(sj, 0) + 1
        kept.append(m)

    if dropped_fam:
        log(f"家族配額（每 24h 最多 {max_fam} 個）：擋咗 {dropped_fam} 個近似題目")
    if dropped_subj:
        log(f"主體配額（每 24h 最多 {max_subj} 個）：擋咗 {dropped_subj} 個同一當事人")

    if not kept:
        log("WARN 所有配額爆滿 —— 放寬限制，改用全部候選")
        for m in markets:
            m.setdefault("_family", family_key(m["question"]))
        return markets
    return kept


def score(m: dict, cfg: dict) -> float:
    sel = cfg["selection"]
    w = sel["weights"]
    mv1 = abs(m["move_1h"])
    mv24 = abs(m["move_24h"])

    # 1 小時異動要有 24 小時佐證先計分。
    # 一場直播緊嘅球賽可以一小時郁 39 點而 24 小時只郁 4 點 ——
    # 嗰個係即時噪音，唔係值得寫嘅結構性異動。
    mv1_scored = mv1
    if sel.get("move_1h_needs_corroboration", True):
        ratio = sel.get("move_1h_corroboration_ratio", 0.35)
        if mv1 > 0 and mv24 < mv1 * ratio:
            mv1_scored = 0.0
            m["_move_1h_uncorroborated"] = True

    s = 0.0
    s += w["move_1h"] * mv1_scored
    s += w["move_24h"] * mv24
    s += w["volume_24hr_log"] * math.log10(max(m["volume_24hr"], 1.0))
    s += w["liquidity_log"] * math.log10(max(m["liquidity"], 1.0))
    # 賠率越接近 0.5，不確定性越高，越有討論價值
    s += w["near_50_bonus"] * (1.0 - abs(m["yes_price"] - 0.5) * 2.0)
    # 快到期嘅盤有緊張感（30 日內線性遞增獎勵）
    d = m.get("days_to_end", 999)
    if d <= 30:
        s += w["resolution_soon"] * (1.0 - d / 30.0)

    # 主題加分 —— 令論點相關嘅類別排得上
    cat_bonus = (sel.get("category_bonus") or {}).get(m.get("category", "other"), 0.0)
    s += cat_bonus

    m["_score"] = s
    m["_score_parts"] = {
        "Δ1h": round(w["move_1h"] * mv1_scored, 2),
        "Δ24h": round(w["move_24h"] * mv24, 2),
        "vol": round(w["volume_24hr_log"] * math.log10(max(m["volume_24hr"], 1.0)), 2),
        "liq": round(w["liquidity_log"] * math.log10(max(m["liquidity"], 1.0)), 2),
        "50/50": round(w["near_50_bonus"] * (1.0 - abs(m["yes_price"] - 0.5) * 2.0), 2),
        "主題": round(cat_bonus, 2),
    }
    return s


def pick(markets: list[dict], cfg: dict, exclude_ids: set[str] | None = None) -> list[dict]:
    """完整選題流程，回傳按分數排序嘅候選清單。"""
    posted = load_posted()
    exclude_ids = exclude_ids or set()

    pool = [m for m in markets if m["condition_id"] not in exclude_ids]
    pool = hard_filter(pool, cfg)
    pool = cooldown_filter(pool, cfg, posted)

    # ⚠️ 一定要先評分排序，先至做配額過濾。
    #    次序調轉嘅話，家族配額會保留「最先遇到」嗰兩個而唔係
    #    「最高分」嗰兩個 —— 等於隨機揀。
    for m in pool:
        score(m, cfg)
    pool.sort(key=lambda x: x["_score"], reverse=True)

    pool = diversity_filter(pool, cfg, posted)

    if pool:
        log("頭 5 名候選：")
        for m in pool[:5]:
            flag = " ⚠1h無佐證" if m.get("_move_1h_uncorroborated") else ""
            log(f"  {m['_score']:6.1f}  {m['yes_price']:.0%}  "
                f"Δ1h={m['move_1h']:+.1%} Δ24h={m['move_24h']:+.1%}  "
                f"${m['volume_24hr']:>10,.0f}  "
                f"[{m['category']}] {m['question'][:52]}{flag}")
    else:
        log("WARN 冇任何市場過到篩選 —— 今次唔出稿")
    return pool
