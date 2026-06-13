import sys, calendar, statistics as st; sys.path.insert(0,".")
from modules.trading import run_setup_backtest as B, smc_live, smc
RP=smc_live.RANGE_PIV; COST=0.0014; START=38000.0; YS=calendar.timegm((2026,1,1,0,0,0))*1000
SLF=0.02  # SL fijo 2%
def resolve(long,e,sl,lo,hi,tp,sel,i,mf):
    if (long and tp<=e) or((not long) and tp>=e): return None
    act=False;end=min(len(sel),i+1+mf)
    for j in range(i+1,end):
        o,h,l=sel[j]["o"],sel[j]["h"],sel[j]["l"]
        if not act:
            if (long and h>=tp) or((not long) and l<=tp):
                if not(l<=hi and h>=lo):return("anulada",None)
            if l<=hi and h>=lo:act=True
            else:continue
        if long:
            if l<=sl:return("perdida",(o if o<sl else sl))
            if h>=tp:return("ganada",tp)
        else:
            if h>=sl:return("perdida",(o if o>sl else sl))
            if l<=tp:return("ganada",tp)
    return("anulada",None)
def stp(long,e,sh,slw,i):
    best=None;pool=sh if long else slw
    for c,idx,pr in pool:
        if c<=i and idx<i and ((pr>e) if long else (pr<e)):
            if best is None or idx>best[0]:best=(idx,pr)
    return best[1] if best else None
trades={"baseline":[],"estructural":[]}
for live,sym in B.SYMBOLS:
    htf={tf:B._load(sym,tf) for tf in set(B.POI_TFS)|set(B.SEL_TFS)};ts={tf:[c["t"] for c in htf[tf]] for tf in htf}
    for stf in B.SEL_TFS:
        sel=htf[stf];sm=B.TF_MS[stf];lr={}
        sh,sll=smc.swing_points(sel,RP);shp=[(p["confirm_idx"],p["idx"],p["price"]) for p in sh];slp=[(p["confirm_idx"],p["idx"],p["price"]) for p in sll]
        start=max(B.WIN,len(sel)-B.BARS.get(stf,3000)-B.MAX_FWD.get(stf,200))
        for i in range(start,len(sel)-1):
            if sel[i]["t"]<YS:continue
            ct=sel[i]["t"]+sm;hm={tf:B._htf_slice(htf[tf],ts[tf],B.TF_MS[tf],ct,B.WIN) for tf in B.POI_TFS}
            try:a=smc_live.analyze(sel[max(0,i-B.WIN+1):i+1],hm,sel[i]["c"],stf)
            except Exception:continue
            p=a.get("tpsl")
            if not p:continue
            k=f"{p['tf']}:{p['dir']}:{round(p['entry_lo'],2)}"
            if k in lr and i<=lr[k]:continue
            lr[k]=i+B.MAX_FWD.get(stf,200);long=p["dir"]=="long";e=p["entry"];mf=B.MAX_FWD.get(stf,200)
            sl=e*(1-SLF) if long else e*(1+SLF)
            tps={"baseline":p["tp"],"estructural":stp(long,e,shp,slp,i)}
            for tpn,tp in tps.items():
                if tp is None:continue
                st_,ex=resolve(long,e,sl,p["entry_lo"],p["entry_hi"],tp,sel,i,mf)
                if st_ not in("ganada","perdida"):continue
                pct=(ex-e)/e if long else (e-ex)/e
                trades[tpn].append({"t":sel[i]["t"],"R":pct/SLF})
def comp(trs,lev):
    trs=sorted(trs,key=lambda x:x["t"]);eq=START;peak=START;mdd=0;low=START;worst=0
    for t in trs:
        f=(t["R"]-COST/SLF)*lev*SLF; worst=min(worst,f*100); eq*= (1+f)
        if eq<=1: return 0,-100,low,worst
        peak=max(peak,eq);mdd=min(mdd,(eq-peak)/peak);low=min(low,eq)
    return eq,mdd*100,low,worst
for tpn in ("estructural","baseline"):
    d=trades[tpn]; win=sum(1 for t in d if t["R"]>0)/len(d)*100; avgR=st.mean([t["R"] for t in d])
    print(f"\n#### TP {tpn} · SL fijo 2% · 2026 · n={len(d)} win={win:.0f}% avgR={avgR:.2f} ####")
    print(f"{'apalanc':9} {'riesgo/tr':9} {'FINAL':>14} {'maxDD%':>7} {'cuenta tocó':>13} {'peor trade%':>11}")
    for lev in (1,3,5,10,20):
        eq,mdd,low,worst=comp(d,lev)
        fin="WIPEOUT" if eq<=1 else f"${eq:,.0f}"
        print(f"{lev:>2}x{'':6} {lev*SLF*100:>7.0f}% {fin:>14} {mdd:>6.0f}% {('$'+format(low,',.0f')):>13} {worst:>10.1f}%")
