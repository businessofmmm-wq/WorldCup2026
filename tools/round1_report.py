import csv, json, math
# All 24 matchday-1 games: (date, home, away, hs, as_, p_home, p_draw, p_away, venue)
G = [
 ("2026-06-11","Mexico","South Africa",2,0,.7597,.1611,.0793,"Mexico City"),
 ("2026-06-11","South Korea","Czech Republic",2,1,.4774,.2616,.2610,"Zapopan"),
 ("2026-06-12","Canada","Bosnia and Herzegovina",1,1,.6533,.2199,.1268,"Toronto"),
 ("2026-06-12","United States","Paraguay",4,1,.3321,.3015,.3665,"Inglewood"),
 ("2026-06-13","Qatar","Switzerland",1,1,.0673,.1267,.8059,"Santa Clara"),
 ("2026-06-13","Brazil","Morocco",1,1,.4784,.2951,.2265,"East Rutherford"),
 ("2026-06-13","Haiti","Scotland",0,1,.2102,.2371,.5528,"Foxborough"),
 ("2026-06-13","Australia","Turkey",2,0,.3817,.2708,.3475,"Vancouver"),
 ("2026-06-14","Germany","Curacao",7,1,.9027,.0694,.0279,"Houston"),
 ("2026-06-14","Ivory Coast","Ecuador",1,0,.1980,.3027,.4993,"Philadelphia"),
 ("2026-06-14","Netherlands","Japan",2,2,.3991,.2722,.3287,"Arlington"),
 ("2026-06-14","Sweden","Tunisia",5,1,.4084,.2915,.3002,"Guadalupe"),
 ("2026-06-15","Belgium","Egypt",1,1,.5932,.2476,.1592,"Seattle"),
 ("2026-06-15","Iran","New Zealand",2,2,.6446,.2302,.1252,"Inglewood"),
 ("2026-06-15","Spain","Cape Verde",0,0,.9161,.0645,.0194,"Atlanta"),
 ("2026-06-15","Saudi Arabia","Uruguay",1,1,.0998,.2267,.6736,"Miami Gardens"),
 ("2026-06-16","France","Senegal",3,1,.5880,.2411,.1709,"East Rutherford"),
 ("2026-06-16","Iraq","Norway",1,4,.1246,.2177,.6577,"Foxborough"),
 ("2026-06-16","Argentina","Algeria",3,0,.7163,.1863,.0974,"Kansas City"),
 ("2026-06-16","Austria","Jordan",3,1,.6178,.2249,.1573,"Santa Clara"),
 ("2026-06-17","Portugal","DR Congo",1,1,.7500,.1739,.0761,"Houston"),
 ("2026-06-17","Uzbekistan","Colombia",1,3,.1079,.2078,.6844,"Mexico City"),
 ("2026-06-17","England","Croatia",4,2,.5549,.2582,.1869,"Arlington"),
 ("2026-06-17","Ghana","Panama",1,0,.2792,.2563,.4645,"Toronto"),
]
def outcome(hs,a): return "home" if hs>a else "away" if hs<a else "draw"
def rps(ph,pd,pa,oc):
    a={"home":(1,0,0),"draw":(0,1,0),"away":(0,0,1)}[oc]
    cp=(ph,ph+pd); ca=(a[0],a[0]+a[1]); return 0.5*sum((x-y)**2 for x,y in zip(cp,ca))
rows=[]
for d,h,a,hs,as_,ph,pd,pa,ven in G:
    oc=outcome(hs,as_); fav=max((("home",ph),("draw",pd),("away",pa)),key=lambda x:x[1])[0]
    p_act={"home":ph,"draw":pd,"away":pa}[oc]
    rows.append(dict(date=d,home=h,away=a,score=f"{hs}-{as_}",hs=hs,away_score=as_,
        result=oc,fav=fav,called=(fav==oc),p_home=ph,p_draw=pd,p_away=pa,
        p_actual=round(p_act,4),rps=round(rps(ph,pd,pa,oc),4),
        goals=hs+as_,margin=abs(hs-as_),venue=ven))
n=len(rows); called=sum(r["called"] for r in rows)
mean_rps=sum(r["rps"] for r in rows)/n
base=sum(rps(1/3,1/3,1/3,r["result"]) for r in rows)/n
draws=sum(r["result"]=="draw" for r in rows); goals=sum(r["goals"] for r in rows)
favwins=sum(1 for r in rows if r["fav"]=="home" and r["result"]=="home" or r["fav"]=="away" and r["result"]==r["result"] and r["fav"]==r["result"])
fav_called=sum(1 for r in rows if r["called"])
upsets=sorted(rows,key=lambda r:r["p_actual"])[:5]
# write CSV + JSON
with open("data/round1_collated.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
json.dump({"rows":rows,"summary":{"n":n,"called":called,"accuracy":round(called/n,3),
    "mean_rps":round(mean_rps,4),"baseline_rps":round(base,4),
    "skill_vs_uniform":round((base-mean_rps)/base,3),"draws":draws,"goals":goals,
    "goals_per_game":round(goals/n,2)}}, open("data/round1_collated.json","w"), indent=1)
# markdown
L=[]
L.append("# Round 1 (matchday 1) — collated · all 24 games\n")
L.append(f"_Every team has played once. Model record **{called}/{n} = {called/n:.0%}** called._\n")
L.append("## Model scorecard\n")
L.append(f"- Outcomes called: **{called}/{n}** ({called/n:.0%})")
L.append(f"- Mean RPS: **{mean_rps:.4f}** (uniform-1/3 baseline {base:.4f} → skill **{(base-mean_rps)/base:+.0%}**)")
L.append(f"- Draws: **{draws}/{n}** ({draws/n:.0%}) · goals/game: **{goals/n:.2f}**\n")
L.append("## Biggest upsets (model's probability of what actually happened)\n")
for r in upsets:
    L.append(f"- {r['home']} {r['score']} {r['away']} → **{r['result']}** "
             f"(model gave it {r['p_actual']:.0%}; favoured {r['fav']})")
L.append("\n## All games\n")
L.append("| Date | Match | Score | Result | Model fav | P(actual) | Called |")
L.append("|---|---|---|---|---|---|:--:|")
for r in rows:
    L.append(f"| {r['date'][5:]} | {r['home']} v {r['away']} | {r['score']} | {r['result']} | "
             f"{r['fav']} ({max(r['p_home'],r['p_draw'],r['p_away']):.0%}) | {r['p_actual']:.0%} | "
             f"{'✓' if r['called'] else '✗'} |")
L.append("\n_Source: WCPA model frozen pre-kickoff calls + results (football-data feed). "
         "Match stats (xG, shots, shotmaps, lineups) require a keyed source — see ROUND1 notes._")
open("ROUND1.md","w").write("\n".join(L)+"\n")
print(f"wrote data/round1_collated.csv, data/round1_collated.json, ROUND1.md")
print(f"record {called}/{n}={called/n:.0%}  meanRPS {mean_rps:.4f} vs base {base:.4f}  draws {draws}  g/g {goals/n:.2f}")
