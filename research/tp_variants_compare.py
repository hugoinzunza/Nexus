import sys, time, calendar; sys.path.insert(0,".")
from modules.trading import run_setup_backtest as B, smc_live, smc
LEV=20;MARGIN=1000.0;NOTIONAL=LEV*MARGIN;COST=0.0014
RP=smc_live.RANGE_PIV

def resolve(long,entry,sl,lo,hi,tp,sel,i,mf):
    # devuelve (status, exit_price) ; status in ganada/perdida/anulada/abierto
    if (long and tp<=entry) or((not long) and tp>=entry): return ("invalido",None)
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
    return("abierto",None)

def struct_tp(long, entry, sh, sl_sw, i):
    # último swing CONFIRMADO antes de i, del lado correcto del precio
    best=None
    pool=sh if long else sl_sw
    for cidx,idx,price in pool:
        if cidx<=i and idx<i and ((price>entry) if long else (price<entry)):
            if best is None or idx>best[0]: best=(idx,price)
    return best[1] if best else None

def collect(symbols, year_start):
    # devuelve dict variante -> lista de trades {R, pct, status}
    variants={"baseline":[], "estructural":[], "2R":[], "3R":[]}
    counts={"setups":0,"struct_na":0}
    for live,sym in symbols:
        htf={tf:B._load(sym,tf) for tf in set(B.POI_TFS)|set(B.SEL_TFS)}
        ts={tf:[c["t"] for c in htf[tf]] for tf in htf}
        for stf in B.SEL_TFS:
            sel=htf[stf];sm=B.TF_MS[stf];lr={}
            sh,sll=smc.swing_points(sel,RP)
            shp=[(p["confirm_idx"],p["idx"],p["price"]) for p in sh]
            slp=[(p["confirm_idx"],p["idx"],p["price"]) for p in sll]
            start=max(B.WIN,len(sel)-B.BARS.get(stf,3000)-B.MAX_FWD.get(stf,200))
            for i in range(start,len(sel)-1):
                if sel[i]["t"]<year_start:continue
                ct=sel[i]["t"]+sm
                hm={tf:B._htf_slice(htf[tf],ts[tf],B.TF_MS[tf],ct,B.WIN) for tf in B.POI_TFS}
                try:a=smc_live.analyze(sel[max(0,i-B.WIN+1):i+1],hm,sel[i]["c"],stf)
                except Exception:continue
                p=a.get("tpsl")
                if not p:continue
                k=f"{p['tf']}:{p['dir']}:{round(p['entry_lo'],2)}"
                if k in lr and i<=lr[k]:continue
                lr[k]=i+B.MAX_FWD.get(stf,200)
                counts["setups"]+=1
                long=p["dir"]=="long";e=p["entry"];sl=p["sl"];risk=abs(e-sl)
                if risk<=0:continue
                st_tp=struct_tp(long,e,shp,slp,i)
                if st_tp is None: counts["struct_na"]+=1
                tps={"baseline":p["tp"],
                     "estructural":st_tp,
                     "2R":e+(2*risk if long else -2*risk),
                     "3R":e+(3*risk if long else -3*risk)}
                mf=B.MAX_FWD.get(stf,200)
                for vn,tp in tps.items():
                    if tp is None: continue
                    status,ex=resolve(long,e,sl,p["entry_lo"],p["entry_hi"],tp,sel,i,mf)
                    if status not in("ganada","perdida"):continue
                    pct=(ex-e)/e if long else (e-ex)/e
                    R=pct*e/risk   # = (exit-entry)/risk con signo correcto
                    variants[vn].append({"t":sel[i]["t"],"R":R,"pct":pct,"win":status=="ganada"})
    return variants,counts

def stats(trs):
    if not trs: return None
    n=len(trs);w=sum(1 for t in trs if t["win"]);totalR=sum(t["R"] for t in trs)
    gw=sum(t["R"] for t in trs if t["R"]>0);gl=abs(sum(t["R"] for t in trs if t["R"]<0)) or 1e-9
    # USD fijo
    eq=MARGIN;peak=MARGIN;mdd=0
    for t in sorted(trs,key=lambda x:x["t"]):
        pnl=NOTIONAL*t["pct"]-NOTIONAL*COST;eq+=pnl;peak=max(peak,eq);mdd=min(mdd,eq-peak)
    net=eq-MARGIN
    # compounding all-in
    ce=MARGIN;ruin=None
    for idx,t in enumerate(sorted(trs,key=lambda x:x["t"])):
        no=LEV*ce;ce+=no*t["pct"]-no*COST
        if ce<=0:ruin=idx+1;ce=0;break
    return dict(n=n,win=w/n*100,avgR=totalR/n,pf=gw/gl,totalR=totalR,usd_fijo=net,mdd=mdd,
                comp=("RUINA#"+str(ruin) if ruin else f"{ce:,.0f}"))

def show(label,variants,counts):
    print(f"\n######## {label}  (setups={counts['setups']}, sin TP estructural={counts['struct_na']}) ########")
    print(f"{'variante':12} {'n':>4} {'win%':>5} {'avgR':>6} {'PF':>5} {'R tot':>7} {'USD fijo':>9} {'maxDD$':>8} {'compound all-in':>16}")
    for vn in ("baseline","estructural","2R","3R"):
        s=stats(variants[vn])
        if not s:continue
        print(f"{vn:12} {s['n']:>4} {s['win']:>5.1f} {s['avgR']:>6.2f} {s['pf']:>5.2f} {s['totalR']:>7.0f} {s['usd_fijo']:>+9.0f} {s['mdd']:>8.0f} {s['comp']:>16}")

YS=calendar.timegm((2026,1,1,0,0,0))*1000
v,c=collect([("BTC_USDT","BTCUSDT")],YS); show("BTC 2026 YTD",v,c)
v,c=collect(B.SYMBOLS,YS); show("BTC+ETH 2026 YTD",v,c)
