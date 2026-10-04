"""Why Q05: the question of the twenty (docs/spikes/v33/questions_v33.json) farthest from Q07 in coverage.

Coverage of each of the 20 battery questions on the NEW architecture's surface, and its distance from Q07.
Q07's set is MEASURED (the 10/4 gpt-5.6-sol run). The other sets are what each question needs on the new
surface: read from its text, cross-checked against the tools it actually reached for in S3_mini (docs/spikes/v1/S3_mini.json, 2026-09-30).
Distance is Jaccard over component sets; the second column counts components Q07 did not touch.

    .venv/bin/python <this dir>/selection.py > selection.txt
"""
Q07 = {"path:lead-direct", "analyze:formula", "analyze:book.column", "compare:previous_ttm", "compare:previous_run",
       "view:rank", "data:financial_facts", "data:runs", "scope:book+sector", "obs:numbers", "obs:scope-mismatch"}
Q = {
 "Q01-amzn-earnings-quality": {"ask:issuer","analyze:formula","analyze:filed_line","compare:series","data:financial_facts","analyze:book.column","data:runs","scope:single","obs:numbers","obs:judgement"},
 "Q02-xom-room-if-oil-falls": {"ask:issuer","ask:risk","multi-specialist","analyze:formula","compare:previous_ttm","verb:filings_search","verb:filings_section","data:filings_text","analyze:book.column","data:runs","metric:price","data:prices","scope:single","obs:numbers","obs:passages"},
 "Q03-nvda-where-cash-goes": {"ask:issuer","analyze:formula","analyze:filed_line","compare:series","verb:filings_search","verb:filings_section","data:financial_facts","data:filings_text","scope:single","obs:numbers","obs:passages"},
 "Q04-lly-margin-pricing-mix-cost": {"ask:issuer","analyze:formula","compare:series","verb:filings_search","verb:filings_section","data:financial_facts","data:filings_text","verb:start","scope:not-on-desk","scope:explicit-list","obs:numbers","obs:passages","obs:absent"},
 "Q05-aapl-risk-and-concentration": {"ask:issuer","verb:filings_search","verb:filings_section","data:filings_text","scope:single","obs:passages","obs:absent","obs:judgement"},
 "Q06-jpm-riskier-than-a-year-ago": {"ask:market","ask:issuer","multi-specialist","metric:price","data:prices","compare:price-then-now","analyze:filed_line","compare:series","data:financial_facts","scope:single","obs:numbers","obs:method-refusal"},
 "Q08-capex-roic-three-way": {"ask:issuer","analyze:formula","compare:series","view:rank","data:financial_facts","scope:explicit-list","data:factors","obs:numbers"},
 "Q09-aapl-working-capital-cycle": {"ask:issuer","analyze:formula","compare:series","view:rank","data:financial_facts","verb:filings_section","data:filings_text","scope:single","obs:numbers","obs:passages","obs:absent"},
 "Q10-msft-leverage-and-rates": {"ask:issuer","ask:risk","multi-specialist","analyze:formula","compare:series","data:financial_facts","verb:filings_search","verb:filings_section","data:filings_text","verb:scenario","data:stress","scope:single","obs:numbers","obs:passages"},
 "Q11-closest-to-issuer-limit": {"ask:risk","data:limits","analyze:book.column","data:runs","view:rank","shape:what-if","scope:whole-book","obs:numbers"},
 "Q12-jpm-vs-peers-not-on-desk": {"ask:issuer","analyze:formula","compare:series","view:rank","data:financial_facts","verb:start","scope:not-on-desk","scope:explicit-list","obs:numbers","obs:absent"},
 "Q13-sell-half-nvda-into-tlt": {"ask:risk","verb:scenario","metric:book","metric:price","data:prices","data:limits","data:stress","data:runs","shape:what-if","scope:whole-book","obs:numbers"},
 "Q14-worst-drawdown-episode": {"ask:market","ask:risk","ask:issuer","multi-specialist","metric:book","data:prices","data:runs","view:rank","shape:episode-window","verb:filings_search","obs:numbers"},
 "Q15-liquidity-and-limits": {"ask:market","ask:risk","multi-specialist","metric:price","data:prices","data:limits","data:runs","view:rank","scope:whole-book","obs:numbers"},
 "Q16-book-beta-change-since-prev": {"ask:risk","metric:price","metric:book","data:prices","data:runs","compare:previous_run","view:rank","scope:whole-book","obs:numbers"},
 "Q17-events-touching-holdings": {"ask:issuer","ask:market","multi-specialist","analyze:book.column","view:rank","data:runs","verb:web_search","data:web","metric:price","data:prices","shape:episode-window","obs:numbers","obs:passages"},
 "Q18-attribution-reconcile": {"ask:risk","metric:book","data:factors","data:runs","view:rank","metric:price","data:prices","obs:numbers"},
 "Q19-aws-share-explains-return": {"ask:issuer","ask:market","multi-specialist","verb:filings_search","data:filings_text","compare:series","metric:price","data:prices","scope:single","obs:numbers","obs:passages","obs:absent","obs:judgement"},
 "Q20-lly-margins-next-year": {"ask:issuer","analyze:formula","compare:series","data:financial_facts","verb:filings_search","verb:filings_section","data:filings_text","scope:single","obs:numbers","obs:passages","obs:judgement"},
}
rows=[]
for tag, s in Q.items():
    inter=s & Q07; union=s | Q07
    rows.append((1-len(inter)/len(union), len(s-Q07), tag, sorted(inter)))
rows.sort(key=lambda r:(-r[0], -r[1]))
print(f"{'question':36} {'distance':>8} {'new':>4}  shared with Q07")
for dist,new,tag,inter in rows:
    print(f"{tag:36} {dist:8.2f} {new:4}  {', '.join(inter) or '-'}")
print("\nQ05 components not touched by Q07:", sorted(Q['Q05-aapl-risk-and-concentration']-Q07))
