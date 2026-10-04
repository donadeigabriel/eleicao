#!/usr/bin/env python3
"""Mapa de calor da apuração presidencial (TSE) -> HTML -> Telegram.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (opcionais; sem eles só gera o HTML)
     TSE_BASE  (padrão https://resultados.tse.jus.br/oficial)
     TSE_CICLO (padrão ele2026)  TSE_ELE (padrão 6257 = Eleição Geral Federal 1º turno)
     Simulado: TSE_BASE=https://resultados-sim.tse.jus.br/simulado/simulado2026 TSE_ELE=21270
     DEBUG=1 imprime as chaves do JSON e os candidatos encontrados.
"""
import os, re, sys, json, unicodedata, datetime as dt
import requests

BASE = os.getenv("TSE_BASE", "https://resultados.tse.jus.br/oficial")
CICLO = os.getenv("TSE_CICLO", "ele2026")
ELE = os.getenv("TSE_ELE", "6257")
OUT = os.getenv("OUT_FILE", "mapa_eleicao.html")
H = {"User-Agent": "Mozilla/5.0 (mapa-eleicao)"}

REGIOES = {
    "Norte": "AC AM AP PA RO RR TO", "Nordeste": "AL BA CE MA PB PE PI RN SE",
    "Centro-Oeste": "DF GO MS MT", "Sudeste": "ES MG RJ SP", "Sul": "PR RS SC",
}
UF_REG = {u: r for r, us in REGIOES.items() for u in us.split()}
IBGE = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
        "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
        "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
        "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


def norm(s):
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().upper()


def walk(o, key):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = walk(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = walk(v, key)
            if r is not None:
                return r


def to_int(x):
    return int(re.sub(r"\D", "", str(x)) or 0)


def to_float(x):
    return float(str(x).replace(".", "").replace(",", ".") or 0)


def get_json(url):
    r = requests.get(url, headers=H, timeout=30)
    r.raise_for_status()
    return r.json()


def url_uf(uf):
    uf = uf.lower()
    return f"{BASE}/{CICLO}/{ELE}/dados/{uf}/{uf}-c0001-e{int(ELE):06d}-u.json"


def candidatos(o, acc=None):
    """Coleta todos os candidatos (dicts com 'vap' e 'sqcand'), em qualquer nível do JSON."""
    acc = [] if acc is None else acc
    if isinstance(o, dict):
        if "vap" in o and "sqcand" in o:
            acc.append(o)
        else:
            for v in o.values():
                candidatos(v, acc)
    elif isinstance(o, list):
        for v in o:
            candidatos(v, acc)
    return acc


def parse(js):
    cands = candidatos(js.get("carg", js))
    if os.getenv("DEBUG"):
        print("chaves:", list(js.keys()), "| candidatos:", [(c.get("nmu"), c.get("vap")) for c in cands])
    lula = flavio = validos = 0
    for c in cands:
        v, n = to_int(c.get("vap", 0)), norm(c.get("nmu", "") + " " + c.get("nm", ""))
        validos += v
        if "LULA" in n:
            lula = v
        elif "BOLSONARO" in n and "FLAVIO" in n:
            flavio = v
    s = js.get("s") if isinstance(js.get("s"), dict) else {}
    ts, st = to_int(s.get("ts", 0)), to_int(s.get("st", 0))
    pct = to_float(s["pst"]) if s.get("pst") is not None else (100.0 * st / ts if ts else 0.0)
    return {"lula": lula, "flavio": flavio, "validos": validos, "pct": min(pct, 100.0), "ts": ts, "st": st, "hg": js.get("hg", ""), "ht": js.get("ht", "")}


def coleta():
    ufs = []
    for uf in sorted(UF_REG) + ["ZZ"]:
        try:
            js = get_json(url_uf(uf))
            d = parse(js)
            if d["pct"] > 0 and (d["lula"] == 0 or d["flavio"] == 0) and not os.path.exists("debug_raw.json"):
                print(f"[suspeito] {uf}: {d} | candidatos:",
                      [(c.get("nmu"), c.get("vap")) for c in candidatos(js)])
                with open("debug_raw.json", "w", encoding="utf-8") as f:
                    json.dump(js, f, ensure_ascii=False)
        except Exception as e:
            print(f"[aviso] {uf}: {e}", file=sys.stderr)
            if uf != "ZZ":
                d = {"lula": 0, "flavio": 0, "validos": 0, "pct": 0.0, "ts": 0, "st": 0}
            else:
                continue
        d.update(uf=uf, reg=UF_REG.get(uf, "Exterior"))
        ufs.append(d)
    return ufs


def geo():
    try:
        u = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
             "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF")
        g = get_json(u)
        for f in g["features"]:
            f["properties"] = {"uf": IBGE.get(str(f["properties"].get("codarea")), "")}
        return g
    except Exception as e:
        print(f"[aviso] malha IBGE indisponível: {e}", file=sys.stderr)
        return {"features": []}


HTML = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Apuração Presidente 2026</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}
header{padding:10px 14px}h1{font-size:18px;margin:0}small{color:#999}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 8px}
.chips button{background:#222;color:#ccc;border:1px solid #444;border-radius:16px;padding:5px 11px;font-size:13px}
.chips button.on{background:#3b5bdb;color:#fff;border-color:#3b5bdb}
main{display:flex;flex-wrap:wrap;gap:12px;padding:0 14px 20px}
#map{flex:1 1 340px;max-width:560px}svg{width:100%;height:auto;background:#181818;border-radius:8px}
path{stroke:#111;stroke-width:.6;cursor:pointer}path:hover{stroke:#fff;stroke-width:1.5}
text{font-size:9px;fill:#000;pointer-events:none;text-anchor:middle}
#side{flex:1 1 320px;min-width:300px}
.card{background:#1c1c1c;border-radius:8px;padding:10px;margin-bottom:10px}
.cols{display:flex;gap:10px}.cols>div{flex:1}h2{font-size:13px;margin:0 0 6px;color:#aaa}
.bar{display:flex;height:16px;border-radius:4px;overflow:hidden;margin:4px 0}
.L{color:#ff6b5e}.F{color:#4cd07d}table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:3px 4px;text-align:right}td:first-child,th:first-child{text-align:left}
tr.off{opacity:.3}th{color:#999;font-weight:500}
</style></head><body>
<header><h1>Apuração Presidente 2026 — mapa de calor</h1><small id="ts"></small></header>
<div class="chips" id="chips"></div>
<main><div id="map"><svg id="svg" viewBox="0 0 600 620"></svg>
<small>Cor = margem entre os dois (até 30 p.p.). Cinza = sem dados.</small></div>
<div id="side"><div class="card" id="tot"></div><div class="card" id="info">Passe o mouse / toque num estado.</div>
<div class="card"><table id="rg"></table></div><div class="card"><table id="tb"></table></div></div></main>
<script>
const D=__DATA__,G=__GEO__,REG=["Norte","Nordeste","Centro-Oeste","Sudeste","Sul","Exterior"];
const late=()=>{const a=D.br&&(D.br.ht||D.br.hg),b=D.ht_ufs||D.hg_ufs;if(!a||!b)return 0;const t=x=>x.split(":").reduce((s,v)=>s*60+ +v,0);return Math.round((t(b)-t(a))/60)};
const $=id=>document.getElementById(id),by={};D.ufs.forEach(u=>by[u.uf]=u);
const n=x=>Math.round(x).toLocaleString("pt-BR"),p=x=>x.toFixed(2).replace(".",",")+"%";
let sel=new Set(REG);const tsf=()=>{const m=Math.max(0,Math.floor((Date.now()-new Date(D.iso))/60000));$("ts").innerHTML="Atualizado em "+D.ts+" · <b style='color:"+(m>12?"#e5534b":"#4cd07d")+"'>há "+m+" min</b> · % = votos válidos · projeção linear por estado"};tsf();setInterval(tsf,15000);
function proj(u){const f=u.pct/100;return f>0?{l:u.lula/f,f:u.flavio/f,v:u.validos/f}:{l:0,f:0,v:0}}
function col(u){if(!u||!u.validos)return"#444";const m=(u.flavio-u.lula)/u.validos*100,t=Math.min(Math.abs(m)/30,1),
b=m>0?[26,152,80]:[215,48,39],e=235;return"rgb("+b.map(c=>Math.round(e+(c-e)*(.25+.75*t))).join(",")+")"}
// mapa
const k=Math.cos(14*Math.PI/180);let pts=[];const polys=G.features.map(f=>{const g=f.geometry,
rings=g.type=="Polygon"?[g.coordinates]:g.coordinates;return{uf:f.properties.uf,rings}});
polys.forEach(o=>o.rings.forEach(r=>r[0].forEach(c=>pts.push(c))));
const xs=pts.map(c=>c[0]*k),ys=pts.map(c=>-c[1]),x0=Math.min(...xs),y0=Math.min(...ys),
s=Math.min(580/(Math.max(...xs)-x0),600/(Math.max(...ys)-y0));
const X=c=>10+(c[0]*k-x0)*s,Y=c=>10+(-c[1]-y0)*s;let svg="";
polys.forEach(o=>{const d=o.rings.map(r=>r.map(ring=>"M"+ring.map(c=>X(c).toFixed(1)+","+Y(c).toFixed(1)).join("L")+"Z").join("")).join("");
let a=[1e9,1e9,-1e9,-1e9];o.rings.forEach(r=>r[0].forEach(c=>{a=[Math.min(a[0],X(c)),Math.min(a[1],Y(c)),Math.max(a[2],X(c)),Math.max(a[3],Y(c))]}));
o.c=[(a[0]+a[2])/2,(a[1]+a[3])/2];svg+=`<path id="p${o.uf}" d="${d}" data-uf="${o.uf}"/>`});
polys.forEach(o=>svg+=`<text x="${o.c[0]}" y="${o.c[1]+3}">${o.uf}</text>`);$("svg").innerHTML=svg;
document.querySelectorAll("path").forEach(e=>{e.onmouseover=e.onclick=()=>info(e.dataset.uf)});
function info(uf){const u=by[uf];if(!u)return;const q=proj(u),v=u.validos||1;
$("info").innerHTML=`<b>${uf}</b> · ${u.reg} · apurado ${p(u.pct)}<br><span class=L>Lula ${p(u.lula/v*100)}</span> (${n(u.lula)}) ·
<span class=F>Flávio ${p(u.flavio/v*100)}</span> (${n(u.flavio)})<br><small>Projeção 100%: Lula ${n(q.l)} · Flávio ${n(q.f)}</small>`}
function bar(l,f,v){const a=l/v*100,b=f/v*100;return`<div class=bar><div style="width:${a}%;background:#d73027"></div>
<div style="width:${100-a-b}%;background:#555"></div><div style="width:${b}%;background:#1a9850"></div></div>`}
function render(){
document.querySelectorAll("path").forEach(e=>{const u=by[e.dataset.uf];e.style.fill=col(u);e.style.opacity=u&&sel.has(u.reg)?1:.12});
const us=D.ufs.filter(u=>sel.has(u.reg));let ts=0,st=0;us.forEach(u=>{ts+=u.ts;st+=u.st});let c={l:0,f:0,v:0},j={l:0,f:0,v:0};
us.forEach(u=>{c.l+=u.lula;c.f+=u.flavio;c.v+=u.validos;const q=proj(u);j.l+=q.l;j.f+=q.f;j.v+=q.v});
const blk=(t,o)=>o.v?`<div><h2>${t}</h2><span class=L>Lula ${p(o.l/o.v*100)}</span><br><small>${n(o.l)}</small><br>
<span class=F>Flávio ${p(o.f/o.v*100)}</span><br><small>${n(o.f)}</small>${bar(o.l,o.f,o.v)}
<small>Diferença: ${n(Math.abs(o.f-o.l))} (${o.f>o.l?"Flávio":"Lula"} à frente)</small></div>`:`<div><h2>${t}</h2>sem dados</div>`;
$("tot").innerHTML=`<h2>Total da seleção · seções apuradas (acumulado) ${ts?p(st/ts*100):"—"}</h2><div class=cols>${blk("Atual (estados até "+(D.hg_ufs||"?")+")",c)}${blk("Projeção 100%",j)}</div>${D.br&&D.br.validos?`<br><small style="color:${late()>2?"#e0b000":"#999"}">${late()>2?"⚠ Arquivo Brasil do TSE DEFASADO ("+late()+" min atrás; dados até "+(D.br.ht||"?")+", gerado "+D.br.hg+"; estados até "+(D.ht_ufs||"?")+"). Vale o Atual acima: ":"Arquivo Brasil do TSE (dados até "+(D.br.ht||"?")+", gerado "+D.br.hg+"): "}<span class=L>Lula ${p(D.br.lula/D.br.validos*100)}</span> · <span class=F>Flávio ${p(D.br.flavio/D.br.validos*100)}</span> · seções ${p(D.br.pct)}</small>`:""}`;
$("tb").innerHTML="<tr><th>UF<th>Apurado<th>Lula<th>Flávio<th>Proj. L<th>Proj. F</tr>"+D.ufs.map(u=>{const v=u.validos||1,q=proj(u),w=q.v||1;
return`<tr class="${sel.has(u.reg)?"":"off"}"><td>${u.uf}<td>${p(u.pct)}<td class=L>${p(u.lula/v*100)}<td class=F>${p(u.flavio/v*100)}<td class=L>${n(q.l)}<td class=F>${n(q.f)}</tr>`}).join("");
const agg=l=>{const t={ts:0,st:0,l:0,f:0,v:0,pl:0,pf:0,pv:0};l.forEach(u=>{t.ts+=u.ts;t.st+=u.st;t.l+=u.lula;t.f+=u.flavio;t.v+=u.validos;const q=proj(u);t.pl+=q.l;t.pf+=q.f;t.pv+=q.v});return t};
const row=(nm,t,off)=>`<tr class="${off?"off":""}"><td>${nm}<td>${t.ts?p(t.st/t.ts*100):"—"}<td class=L>${t.v?p(t.l/t.v*100):"—"}<td class=F>${t.v?p(t.f/t.v*100):"—"}<td class=L>${t.pv?p(t.pl/t.pv*100):"—"}<td class=F>${t.pv?p(t.pf/t.pv*100):"—"}</tr>`;
$("rg").innerHTML="<tr><th>Região (acumulado)<th>Seções<th>Lula<th>Flávio<th>Proj. L<th>Proj. F</tr>"+REG.map(r=>row(r,agg(D.ufs.filter(u=>u.reg==r)),!sel.has(r))).join("")+row("<b>Seleção</b>",agg(us),false);
$("chips").querySelectorAll("button").forEach(b=>b.classList.toggle("on",b.dataset.r=="Todas"?sel.size==REG.length:sel.has(b.dataset.r)))}
$("chips").innerHTML=["Todas",...REG].map(r=>`<button data-r="${r}">${r}</button>`).join("");
$("chips").onclick=e=>{try{setTimeout(()=>localStorage.setItem("selReg",JSON.stringify([...sel])),0)}catch(_){};const r=e.target.dataset.r;if(!r)return;if(r=="Todas")sel=new Set(REG);
else if(sel.size==REG.length)sel=new Set([r]);else sel.has(r)?sel.delete(r):sel.add(r);if(!sel.size)sel=new Set(REG);render()};
try{const x=JSON.parse(localStorage.getItem("selReg")||"null");if(x&&x.length)sel=new Set(x.filter(r=>REG.includes(r)))}catch(e){}
render();
if(typeof location!="undefined"&&location.protocol.startsWith("http"))setTimeout(()=>location.reload(),60000);
</script></body></html>"""


def telegram(path, legenda):
    if os.getenv("NO_TELEGRAM"):
        return
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("Telegram NÃO configurado (faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID); HTML só local.")
        return
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendDocument",
                          data={"chat_id": chat, "caption": legenda}, files={"document": f}, timeout=60)
    r.raise_for_status()
    print("Enviado ao Telegram.")


OFF_BRT = {"AC": 2, "AM": 1, "RR": 1, "RO": 1, "MT": 1, "MS": 1}  # ht dos estados vem na hora local


def ht_brt(u):
    try:
        a, b, c = u.get("ht", "").split(":")
        return f"{(int(a) + OFF_BRT.get(u['uf'], 0)) % 24:02d}:{b}:{c}"
    except Exception:
        return ""


def main():
    ufs = coleta()
    try:
        br = parse(get_json(url_uf("br")))
    except Exception as e:
        print(f"[aviso] arquivo BR: {e}", file=sys.stderr)
        br = None
    agora = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S (Brasília)")
    html = HTML.replace("__DATA__", json.dumps({"ufs": ufs, "ts": agora, "iso": dt.datetime.now(dt.timezone.utc).isoformat(), "br": br, "hg_ufs": max((u.get("hg", "") for u in ufs), default=""), "ht_ufs": max((ht_brt(u) for u in ufs if u["uf"] != "ZZ"), default="")}, ensure_ascii=False)) \
               .replace("__GEO__", json.dumps(geo(), separators=(",", ":")))
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    L, F, V = (sum(u[k] for u in ufs) for k in ("lula", "flavio", "validos"))
    leg = f"Apuração presidente — {agora}\nLula {100*L/V:.2f}% | Flávio {100*F/V:.2f}%" if V else f"Apuração — {agora} (sem dados ainda)"
    if br and br["validos"]:
        leg += (f"\nArquivo BR do TSE: Lula {100*br['lula']/br['validos']:.2f}% | "
                f"Flávio {100*br['flavio']/br['validos']:.2f}% | seções {br['pct']:.2f}% (gerado {br['hg']})")
        try:
            t = lambda x: sum(int(v) * m for v, m in zip(x.split(":"), (3600, 60, 1)))
            hu = max(u.get("hg", "") for u in ufs)
            if t(hu) - t(br["hg"]) > 120:
                leg += f"\n⚠ Arquivo Brasil defasado {(t(hu)-t(br['hg']))//60} min vs estados ({hu}); vale a soma dos estados"
        except Exception:
            pass
        print(f"Soma UFs: L={L} F={F} V={V} | BR: L={br['lula']} F={br['flavio']} V={br['validos']}")
    print(leg)
    telegram(OUT, leg)
    if os.path.exists("debug_raw.json"):
        telegram("debug_raw.json", "DEBUG: JSON bruto de uma UF (leitura suspeita)")


if __name__ == "__main__":
    main()
