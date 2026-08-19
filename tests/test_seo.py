"""seo.py 測試 —— 針對 2026 年 X 嘅實際機制。"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import seo

FAILED = []
def check(name, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not cond: FAILED.append(name)

GOOD = """The Fed market is pricing a 29% chance of a rate hike next month and a 1%
chance of a cut. Not a typo. Hike.

Polymarket's September FOMC board, right now: no change 72c, hike 25bp 29c, cut
25bp 1.0c, and half a cent each on the two tail outcomes. Thirty-seven million
dollars of volume across the board. Kalshi has the same top two at 71.5 and 28.5.

Now add those five numbers up. 102.8.

The outcomes are mutually exclusive and cover every possibility, so they have to
sum to 100. That gap is not a gift. Part of it is display rounding, the rest is
spread and fees, and it sits there because capital would be locked until 16
September to collect it.

What I find more interesting than the 2.8 is the 29 versus the 1.

Either inflation reaccelerated more than the consensus admits, or that 29 is
longshot froth of exactly the kind that shows up in this data.

We find out on 16 September. I will post the resolution either way."""

print("── 1. 好稿應該全過 ──")
r = seo.analyse(GOOD, "", {"question": "Fed Decision in September?"}, tier="discussion")
check("通過", r.ok, r.summary)
check("認到 Federal Reserve", "Federal Reserve" in r.entities, str(r.entities))
check("認到 Polymarket", "Polymarket" in r.entities)
check("認到 Kalshi", "Kalshi" in r.entities)
check("零 hashtag", r.hashtags == [])

print("\n── 2. 實體埋喺 280 字之後 = 問題 ──")
buried = ("Something happened today that I thought was worth writing up in a "
          "little detail, because it took me a while to work out what was going "
          "on and I suspect the same thing has caught other people out before. "
          "It started when I was going through the usual overnight numbers and "
          "noticed one line that did not look right at all to me.\n\n"
          "The Federal Reserve board on Polymarket sums to 102.8 with 29% on a hike.")
r2 = seo.analyse(buried, "", {"question": "Fed"}, tier="discussion")
check("捉到實體太遲出現",
      any("主要實體" in p for p in r2.problems), str(r2.problems))

print("\n── 3. 可見範圍冇數字 = 問題 ──")
nonum = ("The Federal Reserve board on Polymarket looks unusual today. "
         "The distribution across outcomes is not what most commentary would "
         "lead you to expect, and the shape of it is worth pausing on before "
         "anyone reaches for an explanation of why it might be the case here. "
         "Either inflation reaccelerated, or it is froth.\n\nSum was 102.8.")
r3 = seo.analyse(nonum, "", None, tier="discussion")
check("捉到可見範圍冇數字",
      any("具體數字" in p for p in r3.problems), str(r3.problems))

print("\n── 4. Hashtag 紀律 ──")
r4 = seo.analyse(GOOD + "\n\n#Fed #FOMC #Polymarket #crypto", "", None, tier="move")
check("4 個 hashtag 被判問題",
      any("hashtag" in p for p in r4.problems), str(r4.problems))
check("數到 4 個", len(r4.hashtags) == 4, str(r4.hashtags))

r4b = seo.analyse(GOOD + "\n\n#FOMC", "", None, tier="move")
check("1 個 hashtag 只提示唔判錯", r4b.ok and any("hashtag" in h for h in r4b.hints),
      f"ok={r4b.ok} hints={r4b.hints}")

print("\n── 5. 回覆鈎 ──")
nohook = ("The Federal Reserve board on Polymarket summed to 102.8 today with 29% "
          "priced on a September hike and 1% on a cut. Volume across the board was "
          "37 million dollars. Kalshi showed the same top two outcomes at 71.5 and "
          "28.5. The 2.8 overround reflects spread and fees. Nothing further to "
          "note about the distribution. The scan completed without incident and "
          "the figures were logged in the usual place for later reference.")
r5 = seo.analyse(nohook, "", None, tier="discussion")
check("討論型冇回覆鈎 = 問題",
      any("回覆鈎" in p for p in r5.problems), str(r5.problems))
r5b = seo.analyse(nohook, "", None, tier="anchor")
check("anchor 型冇回覆鈎只係提示",
      not any("回覆鈎" in p for p in r5b.problems), str(r5b.problems))

print("\n── 6. 長度 ──")
short = "Fed board sums to 102.8. 29% on a hike. Volume 37 million. Interesting?"
r6 = seo.analyse(short, "", None, tier="move")
check("太短被判問題", any("字 ——" in p or "太短" in p for p in r6.problems), str(r6.problems))

print("\n── 7. 重寫指令 ──")
instr = seo.rewrite_instruction(r3)
check("有問題就生成指令", len(instr) > 50)
check("指令含 280 提示", "280" in instr)
check("冇問題就唔生成指令", seo.rewrite_instruction(r) == "")

print("\n── 8. 實體別名 ──")
check("『FOMC』認到 Federal Reserve",
      "Federal Reserve" in seo.detect_entities("The FOMC meets in September"))
check("『BTC』認到 Bitcoin", "Bitcoin" in seo.detect_entities("BTC at 100k"))
check("『scotus』認到 Supreme Court",
      "Supreme Court" in seo.detect_entities("scotus ruling due"))
check("唔會亂認", seo.detect_entities("nothing relevant here at all") == [])
check("字界正確：『federated』唔應該認到 Fed",
      "Federal Reserve" not in seo.detect_entities("a federated system"))

print("\n" + ("🎉 seo 全部通過" if not FAILED else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
