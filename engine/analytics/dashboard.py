"""dashboard.py — 관리자 방문 분석 대시보드(정적 HTML, 자기완결형).

외부 요청 0(인라인 CSS/JS/SVG) — HTTP Basic Auth 뒤에서 서빙되므로 CDN/폰트 없이 동작.
data.json(같은 디렉토리) 을 fetch 해 렌더. 다크 테마(engine/report.py 와 일관).
"""
from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>stack. 방문 분석 (admin)</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--bd:#2a2f3a;--tx:#e7ebf2;--mut:#9aa4b2;
--pv:#4c9ffe;--uq:#4ade80;--bot:#f5b942;--dl:#a78bfa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:26px 20px 80px}
h1{font-size:22px;margin:0 0 2px}
.sub{color:var(--mut);font-size:12.5px;margin:0 0 18px}
h2{font-size:14.5px;margin:26px 0 10px;border-bottom:1px solid var(--bd);padding-bottom:6px;
display:flex;justify-content:space-between;align-items:center}
h2 .hint{font-weight:400;color:var(--mut);font-size:11.5px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 16px}
.bar-toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:0 0 16px}
button{background:#20242e;color:var(--tx);border:1px solid var(--bd);border-radius:8px;
padding:7px 12px;font-size:12.5px;cursor:pointer;font-family:inherit}
button:hover{border-color:#3a4150}
button.on{background:var(--pv);border-color:var(--pv);color:#04121f;font-weight:600}
.excl{margin-left:auto;display:flex;gap:8px;align-items:center;font-size:12px;color:var(--mut)}
.pill{padding:3px 9px;border-radius:999px;font-size:11.5px;font-weight:600}
.pill.ex{background:rgba(74,222,128,.15);color:#8ff0b5;border:1px solid rgba(74,222,128,.35)}
.pill.in{background:rgba(245,185,66,.12);color:#f0d79a;border:1px solid rgba(245,185,66,.3)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:13px 15px}
.kpi b{display:block;font-size:24px;font-variant-numeric:tabular-nums;letter-spacing:-.5px}
.kpi span{font-size:11.5px;color:var(--mut)}
.kpi.accent b{color:var(--pv)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}}
svg{display:block;width:100%;height:auto}
.legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin:2px 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.rows{display:flex;flex-direction:column;gap:7px}
.row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;font-size:13px}
.row .lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .track{grid-column:1/-1;height:6px;background:#20242e;border-radius:4px;overflow:hidden}
.row .fill{height:100%;background:var(--pv);border-radius:4px}
.row .num{font-variant-numeric:tabular-nums;color:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--bd);white-space:nowrap}
th{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.03em}
td.path{white-space:normal;max-width:340px;word-break:break-all}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.st{padding:1px 7px;border-radius:5px;font-size:11px;font-weight:600}
.st.ok{background:rgba(74,222,128,.14);color:#8ff0b5}.st.rd{background:rgba(255,120,120,.14);color:#ffb3b3}
.st.wn{background:rgba(245,185,66,.16);color:#f0d79a}.st.mut{background:#20242e;color:var(--mut)}
.scroll{overflow-x:auto}
.empty{color:var(--mut);font-size:13px;padding:10px 2px}
.foot{color:var(--mut);font-size:11.5px;margin-top:34px;line-height:1.7}
.tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:5px;background:#20242e;color:var(--mut);margin-left:6px}
details{margin-top:8px}summary{cursor:pointer;color:var(--mut);font-size:12.5px}
code{background:#20242e;padding:1px 6px;border-radius:5px;font-size:11.5px;color:#cbd5e1;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
</style></head><body><div class="wrap">
<h1>stack. 방문 분석 <span class="tag" id="dom"></span></h1>
<p class="sub" id="sub">불러오는 중…</p>

<div class="bar-toolbar">
  <span style="font-size:12px;color:var(--mut)">추세 기간</span>
  <button data-range="7">7일</button>
  <button data-range="30" class="on">30일</button>
  <button data-range="90">90일</button>
  <button id="refresh">↻ 새로고침</button>
  <div class="excl">
    <span id="exState"></span>
    <button id="exBtn"></button>
  </div>
</div>

<div class="kpis" id="kpis"></div>

<h2>데이터 수집 주기 <span class="hint" id="batchHint"></span></h2>
<div class="card scroll"><table id="batch"></table></div>

<h2>방문 추세 <span class="hint" id="trendHint"></span></h2>
<div class="card">
  <div class="legend">
    <span><i style="background:var(--pv)"></i>페이지뷰</span>
    <span><i style="background:var(--uq)"></i>순방문자</span>
    <span><i style="background:var(--bot)"></i>봇(제외)</span>
  </div>
  <div id="trend"></div>
</div>

<div class="grid2" style="margin-top:16px">
  <div>
    <h2>페이지별 접속 <span class="hint">누적 페이지뷰</span></h2>
    <div class="card"><div class="rows" id="pages"></div></div>
  </div>
  <div>
    <h2>시간대 분포 <span class="hint">최근 7일</span></h2>
    <div class="card"><div id="hourly"></div></div>
    <h2 style="margin-top:16px">기기 · 브라우저 <span class="hint">최근 30일</span></h2>
    <div class="card"><div class="rows" id="devices"></div><div class="rows" id="browsers" style="margin-top:12px"></div></div>
  </div>
</div>

<div class="grid2" style="margin-top:16px">
  <div>
    <h2>유입 경로 <span class="hint">최근 30일 · 봇 제외</span></h2>
    <div class="card"><div class="rows" id="refs"></div></div>
  </div>
  <div>
    <h2>봇 · 스캐너 <span class="hint">최근 30일 · 집계 제외됨</span></h2>
    <div class="card"><div class="rows" id="bots"></div></div>
  </div>
</div>

<h2>최근 접속 로그 <span class="hint">나·봇 제외 · 사람 방문만</span></h2>
<div class="card scroll"><table id="recent"></table></div>

<p class="foot" id="foot"></p>
</div>

<script>
const $=(s)=>document.querySelector(s);
const fmt=(n)=>(n==null?"–":n.toLocaleString());
const esc=(s)=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let DATA=null, RANGE=30;

function cookieName(){ return (DATA&&DATA.exclude&&DATA.exclude.cookie)||"noana"; }
function isExcluded(){ return document.cookie.split(";").some(c=>c.trim()===cookieName()+"=1"); }
function renderExclude(){
  const on=isExcluded();
  $("#exState").innerHTML = on
    ? '<span class="pill ex">이 브라우저: 집계 제외됨</span>'
    : '<span class="pill in">이 브라우저: 집계됨</span>';
  $("#exBtn").textContent = on ? "집계에 다시 포함" : "이 브라우저 집계 제외";
}
$("#exBtn").onclick=()=>{
  const n=cookieName();
  if(isExcluded()) document.cookie=n+"=; path=/; max-age=0; SameSite=Lax";
  else document.cookie=n+"=1; path=/; max-age=63072000; SameSite=Lax";
  renderExclude();
};

// ---- SVG 라인 차트 ----
function lineChart(el, days){
  const W=720,H=250,PL=44,PR=14,PT=14,PB=26;
  const iw=W-PL-PR, ih=H-PT-PB;
  const data=(DATA.trend||[]).slice(-days);
  if(!data.length){el.innerHTML='<div class="empty">데이터 없음</div>';return;}
  const maxV=Math.max(1,...data.map(d=>Math.max(d.pv,d.uniq,d.bots)));
  const nice=Math.pow(10,Math.floor(Math.log10(maxV)));
  const top=Math.ceil(maxV/nice)*nice||maxV;
  const n=data.length;
  const X=(i)=>PL+(n<=1?iw/2:iw*i/(n-1));
  const Y=(v)=>PT+ih-(ih*v/top);
  const path=(key)=>data.map((d,i)=>(i?"L":"M")+X(i).toFixed(1)+" "+Y(d[key]).toFixed(1)).join(" ");
  const area=(key)=>"M"+X(0).toFixed(1)+" "+Y(0).toFixed(1)+" "+data.map((d,i)=>"L"+X(i).toFixed(1)+" "+Y(d[key]).toFixed(1)).join(" ")+" L"+X(n-1).toFixed(1)+" "+Y(0).toFixed(1)+" Z";
  let grid="";const ticks=top<=4?top:4;
  for(let t=0;t<=ticks;t++){const v=top*t/ticks,y=Y(v);
    grid+=`<line x1="${PL}" y1="${y.toFixed(1)}" x2="${W-PR}" y2="${y.toFixed(1)}" stroke="#242833"/>`+
          `<text x="${PL-8}" y="${(y+4).toFixed(1)}" fill="#6b7280" font-size="10" text-anchor="end">${Math.round(v)}</text>`;}
  // x 라벨(처음/중간/끝)
  let xl="";[0,Math.floor((n-1)/2),n-1].forEach(i=>{if(i>=0&&i<n)
    xl+=`<text x="${X(i).toFixed(1)}" y="${H-8}" fill="#6b7280" font-size="10" text-anchor="middle">${data[i].date.slice(5)}</text>`;});
  // bot 바
  let bars="";const bw=Math.max(1,iw/n*0.5);
  data.forEach((d,i)=>{if(d.bots>0){const y=Y(d.bots);bars+=`<rect x="${(X(i)-bw/2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${(PT+ih-y).toFixed(1)}" fill="var(--bot)" opacity=".35"/>`;}});
  // 점 + 툴팁
  let dots="";data.forEach((d,i)=>{
    dots+=`<circle cx="${X(i).toFixed(1)}" cy="${Y(d.pv).toFixed(1)}" r="2.6" fill="var(--pv)"><title>${d.date} · PV ${d.pv} · 순방문 ${d.uniq} · 봇 ${d.bots}</title></circle>`;
    dots+=`<circle cx="${X(i).toFixed(1)}" cy="${Y(d.uniq).toFixed(1)}" r="2.2" fill="var(--uq)"></circle>`;});
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
    ${grid}${bars}
    <path d="${area('pv')}" fill="var(--pv)" opacity=".10"/>
    <path d="${path('pv')}" fill="none" stroke="var(--pv)" stroke-width="2"/>
    <path d="${path('uniq')}" fill="none" stroke="var(--uq)" stroke-width="2"/>
    ${dots}${xl}</svg>`;
}

function barRows(el, items, labelKey, numKey){
  if(!items||!items.length){el.innerHTML='<div class="empty">데이터 없음</div>';return;}
  const max=Math.max(1,...items.map(i=>i[numKey]));
  el.innerHTML=items.map(it=>{
    const w=(100*it[numKey]/max).toFixed(1);
    return `<div class="row"><div class="lbl" title="${esc(it[labelKey])}">${esc(it[labelKey])}</div><div class="num">${fmt(it[numKey])}</div><div class="track"><div class="fill" style="width:${w}%"></div></div></div>`;
  }).join("");
}

function hourly(el, arr){
  const W=340,H=140,PB=18,PT=6,PL=6,PR=6,iw=W-PL-PR,ih=H-PT-PB;
  const max=Math.max(1,...arr);const bw=iw/24*0.72;
  let bars="",lab="";
  arr.forEach((v,h)=>{const x=PL+iw*h/24+ (iw/24-bw)/2;const bh=ih*v/max;const y=PT+ih-bh;
    bars+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="1.5" fill="var(--pv)" opacity="${v?0.9:0.15}"><title>${h}시 · ${v}</title></rect>`;
    if(h%6===0)lab+=`<text x="${(PL+iw*h/24).toFixed(1)}" y="${H-5}" fill="#6b7280" font-size="9">${h}시</text>`;});
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}">${bars}${lab}</svg>`;
}

function devices(el, dev){
  const map={desktop:"데스크톱",mobile:"모바일",tablet:"태블릿",other:"기타"};
  const items=Object.keys(map).map(k=>({label:map[k],count:dev[k]||0})).filter(i=>i.count>0);
  barRows(el, items, "label", "count");
}

function batch(el, b){
  const jobs=(b&&b.jobs)||[];
  if(!jobs.length){el.innerHTML='<tr><td class="empty">배치 정보 없음</td></tr>';return;}
  const bd=(j)=>{
    const map={ok:["ok","✓ 성공"],fail:["rd","✗ 실패"],unknown:["mut","— 정보없음"]};
    const m=map[j.state]||map.unknown;
    let s=`<span class="st ${m[0]}">${m[1]}</span>`;
    if(j.stale) s+=' <span class="st wn" title="예상 주기보다 오래 미실행">⚠ 지연</span>';
    return s;
  };
  el.innerHTML='<thead><tr><th>배치</th><th>주기</th><th>최근 상태</th><th>마지막 실행</th><th>cron · 내용</th></tr></thead><tbody>'+
    jobs.map(j=>`<tr><td>${esc(j.name)}</td><td>${esc(j.schedule)}</td>`+
      `<td>${bd(j)}</td><td>${esc(j.last_run||"—")}</td>`+
      `<td class="path"><code>${esc(j.cron)}</code> ${esc(j.detail)}</td></tr>`).join("")+'</tbody>';
}

function recent(el, rows){
  if(!rows||!rows.length){el.innerHTML='<tr><td class="empty">아직 사람 방문 기록이 없습니다. (봇·내 방문 제외)</td></tr>';return;}
  el.innerHTML='<thead><tr><th>시간</th><th>페이지</th><th>상태</th><th>기기</th><th>브라우저</th><th>유입</th><th>IP</th></tr></thead><tbody>'+
    rows.map(r=>`<tr><td>${esc(r.t)}</td><td class="path">${esc(r.label)}</td>`+
      `<td><span class="st ${r.status<400?'ok':'rd'}">${r.status}</span></td>`+
      `<td>${esc(r.device)}</td><td>${esc(r.browser)}</td><td>${esc(r.ref)}</td><td>${esc(r.ip)}</td></tr>`).join("")+
    '</tbody>';
}

function render(){
  const s=DATA.summary;
  $("#dom").textContent=DATA.domain||"";
  $("#sub").innerHTML=`생성 ${esc(DATA.generated_at)} · 집계 시작 ${esc(DATA.first_seen||"—")} · `+
    `나(쿠키 <code>${esc(DATA.exclude.cookie)}</code> · IP ${(DATA.exclude.ips||[]).map(esc).join(", ")||"없음"})·봇 제외`;
  $("#kpis").innerHTML=[
    ["accent",s.today_pv,"오늘 페이지뷰"],
    ["",s.pv_7d,"7일 페이지뷰"],
    ["",s.uniq_7d,"7일 순방문자"],
    ["",s.pv_30d,"30일 페이지뷰"],
    ["",s.uniq_30d,"30일 순방문자"],
    ["",s.all_time_pv,"누적 페이지뷰"],
    ["",s.bots_7d,"봇 차단(7일)"],
    ["",s.self_excluded,"내 방문 제외"],
  ].map(([c,v,l])=>`<div class="kpi ${c}"><b>${fmt(v)}</b><span>${l}</span></div>`).join("");
  batch($("#batch"),DATA.batch);
  const bjobs=(DATA.batch&&DATA.batch.jobs)||[];
  const nf=bjobs.filter(j=>j.state==="fail").length, ns=bjobs.filter(j=>j.stale).length;
  const health=nf?("⚠ "+nf+"건 실패"):ns?("⚠ "+ns+"건 지연"):(bjobs.length?"모두 정상":"");
  $("#batchHint").textContent=((DATA.batch&&DATA.batch.note)||"")+(health?" · "+health:"");
  lineChart($("#trend"),RANGE);
  $("#trendHint").textContent="최근 "+RANGE+"일";
  barRows($("#pages"),(DATA.top_pages||[]).slice(0,12),"label","pv");
  hourly($("#hourly"),DATA.hourly||new Array(24).fill(0));
  devices($("#devices"),DATA.devices||{});
  barRows($("#browsers"),DATA.browsers||[],"name","count");
  barRows($("#refs"),(DATA.referrers||[]).map(r=>({label:r.host,count:r.count})),"label","count");
  barRows($("#bots"),(DATA.bots||[]).map(b=>({label:b.name,count:b.count})),"label","count");
  recent($("#recent"),DATA.recent||[]);
  $("#foot").innerHTML="서버사이드 nginx 로그 분석(클라이언트 스크립트 없음 → Core Web Vitals 영향 0). "+
    "IP 는 마지막 옥텟 마스킹. HTTP Basic Auth 로 보호되며 검색엔진 비색인(noindex). "+
    "‘이 브라우저 집계 제외’ 는 이 도메인에 <code>"+esc(DATA.exclude.cookie)+"=1</code> 쿠키를 심어 이후 방문을 제외합니다.";
  renderExclude();
}

async function load(){
  try{
    // 페이지 URL 에 자격증명(admin:pass@)이 박혀 있어도 fetch 가 거부되지 않도록 제거
    const u=new URL("data.json",location.href);
    u.username="";u.password="";u.searchParams.set("_",Date.now());
    const r=await fetch(u,{cache:"no-store"});
    DATA=await r.json();
    render();
  }catch(e){ $("#sub").textContent="data.json 을 불러오지 못했습니다: "+e; }
}
document.querySelectorAll("[data-range]").forEach(b=>b.onclick=()=>{
  RANGE=+b.dataset.range;
  document.querySelectorAll("[data-range]").forEach(x=>x.classList.toggle("on",x===b));
  if(DATA){lineChart($("#trend"),RANGE);$("#trendHint").textContent="최근 "+RANGE+"일";}
});
$("#refresh").onclick=load;
load();
setInterval(load,60000);
</script></body></html>
"""
