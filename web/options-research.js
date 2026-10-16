(()=>{
'use strict';
const ROOT_ID='options-research';
const q=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toFixed(2);
const pct=v=>v==null||!Number.isFinite(Number(v))?'—':(Number(v)*100).toFixed(1)+'%';
const signed=v=>v==null||!Number.isFinite(Number(v))?'—':`<span class="${Number(v)>0?'up':Number(v)<0?'down':''}">${Number(v)>=0?'+':''}${num(v)}</span>`;
const ret=v=>v==null||!Number.isFinite(Number(v))?'—':`<span class="${Number(v)>0?'up':Number(v)<0?'down':''}">${Number(v)>=0?'+':''}${(Number(v)*100).toFixed(2)}%</span>`;
let payload=null;

function install(){
 const nav=document.querySelector('main nav');
 if(!nav||q(ROOT_ID)) return;
 const button=document.createElement('button');
 button.type='button'; button.dataset.tab=ROOT_ID; button.textContent='Options Research';
 const source=q('source'); nav.insertBefore(button,source||null);
 const section=document.createElement('section'); section.id=ROOT_ID; section.className='hidden';
 section.innerHTML=`
  <div class="note"><strong>Options Research · sólo lectura.</strong> Cruza Jev con Frozen, PUT v0.2, H09 y Multi-Symbol. Discovery no cuenta como validación prospectiva y esta pestaña no puede enviar órdenes ni cambiar thresholds.</div>
  <div class="filters">
   <label>Sesión <input id="or-day" type="date"></label>
   <label>Activo <select id="or-symbol"><option value="">Todos</option></select></label>
   <label>Dirección <select id="or-side"><option value="">Todas</option><option>CALL</option><option>PUT</option></select></label>
   <label>Fuente <select id="or-source"><option value="">Todas</option><option>Jev</option><option>Frozen</option><option>PUT v0.2</option><option>H09</option><option>Multi-Symbol</option></select></label>
   <label>Evidencia <select id="or-evidence"><option value="">Toda</option><option>DISCOVERY</option><option>PROSPECTIVE</option><option>PAPER</option></select></label>
   <button type="button" id="or-refresh">Actualizar</button>
  </div>
  <p id="or-health" class="muted" role="status">Cargando Options Research…</p>
  <div class="stats" id="or-stats"></div>
  <div class="grid" style="margin-bottom:20px">
   <div class="card"><h2>META LIVE <small>· ACCEPT / WAIT / BLOCK · sólo shadow</small></h2><div class="stats" id="or-meta-stats" style="margin-bottom:14px"></div><p id="or-meta-context" class="muted"></p><div id="or-meta-live" class="table"></div></div>
   <div class="card"><h2>TTT / Hysteresis <small>· Signal Episode Engine</small></h2><p class="muted">H01 confirma la primera señal limpia; H09/Multi requieren persistencia de activaciones. Hysteresis nunca sobreescribe un BLOCK/WAIT de Meta.</p><div id="or-episodes" class="table"></div></div>
  </div>
  <div class="card" style="margin-bottom:20px"><h2>Resultados por estrategia <small>· discovery, prospectivo y paper separados</small></h2><div id="or-strategies" class="table"></div></div>
  <div class="grid">
   <div class="card"><h2>Jev frente a Options Research</h2><div id="or-groups" class="table"></div></div>
   <div class="card"><h2>Resultados por confianza Jev</h2><div id="or-confidence" class="table"></div></div>
  </div>
  <div class="card" style="margin-top:20px"><h2>Resultados por activo</h2><div id="or-symbols" class="table"></div></div>
  <div class="card" style="margin-top:20px"><h2>Coincidencias por señal <small>· ventana temporal ±90 s, mismo activo</small></h2><div id="or-signals" class="table"></div></div>
  <div class="card" style="margin-top:20px"><h2>H09 PUT · H09A vs H09B</h2><div id="or-h09" class="table"></div><p class="muted">H09 sigue SHADOW_ONLY. El retorno a 60m y TP10-before-SL10 se muestran por separado porque una buena dirección puede tocar el stop primero.</p></div>
  <div class="card" style="margin-top:20px"><h2>Multi-Symbol · familias de investigación</h2><div id="or-multi" class="table"></div><p class="muted">Las diferencias retrospectivas por activo son discovery. Ningún candidato se promueve automáticamente a Alpaca.</p></div>`;
 document.querySelector('main').insertBefore(section,q('setup'));
 document.querySelectorAll('nav [data-tab]').forEach(b=>{if(b!==button)b.addEventListener('click',()=>section.classList.add('hidden'));});
 button.addEventListener('click',()=>activate(button));
 q('or-refresh').addEventListener('click',load);
 ['or-symbol','or-side','or-source','or-evidence'].forEach(id=>q(id).addEventListener('change',render));
 q('or-day').addEventListener('change',load);
}

function activate(button){
 document.querySelectorAll('nav [data-tab]').forEach(v=>v.classList.toggle('active',v===button));
 document.querySelectorAll('main > section').forEach(section=>section.classList.toggle('hidden',section.id!==ROOT_ID));
 load();
}

function visibleStrategies(){
 if(!payload) return [];
 const side=q('or-side').value,source=q('or-source').value,evidence=q('or-evidence').value;
 return payload.strategy_results.filter(r=>(!side||r.side===side)&&(!source||r.source===source)&&(!evidence||r.evidence===evidence));
}
function visibleSignals(){
 if(!payload) return [];
 const symbol=q('or-symbol').value,side=q('or-side').value,source=q('or-source').value;
 return payload.comparison.rows.filter(r=>(!symbol||r.symbol===symbol)&&(!side||r.options_side===side)&&(!source||r.options_source===source)&&(!q('or-evidence').value||r.options_evidence===q('or-evidence').value));
}
function table(headers,rows){
 return `<table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
}
function metaSourceMatches(row){
 const filter=q('or-source').value; if(!filter)return true;
 const map={'Frozen':'H01','H09':'H09','Multi-Symbol':'MULTI'};
 return map[filter]?row.source===map[filter]:false;
}
function renderMetaLive(){
 const bundle=payload?.meta_live||{},meta=bundle.meta||{},engine=bundle.episode_engine||{};
 const symbol=q('or-symbol').value,side=q('or-side').value;
 const rows=(meta.decisions||[]).filter(r=>(!symbol||r.symbol===symbol)&&(!side||r.side===side)&&metaSourceMatches(r));
 const episodes=(engine.episodes||[]).filter(r=>(!symbol||r.symbol===symbol)&&(!side||r.side===side)&&metaSourceMatches(r));
 const counts={ACCEPT:0,WAIT:0,BLOCK:0}; rows.forEach(r=>{if(counts[r.decision]!=null)counts[r.decision]++});
 q('or-meta-stats').innerHTML=[['ACCEPT',counts.ACCEPT],['WAIT',counts.WAIT],['BLOCK',counts.BLOCK],['TTT confirmados',episodes.filter(r=>String(r.ttt_state||'').startsWith('CONFIRMED')).length]].map(([k,v])=>`<div class="card" style="padding:12px"><small>${esc(k)}</small><div class="value" style="font-size:22px">${esc(v)}</div></div>`).join('');
 const ctx=meta.latest_context||{};
 q('or-meta-context').textContent=meta.version?`Meta ${meta.mode||'—'} · contexto ${ctx.market_regime||'UNKNOWN'} · SPY ${pct(ctx.spy_from_open)} · QQQ ${pct(ctx.qqq_from_open)} · IWM ${pct(ctx.iwm_from_open)} · VIX ${pct(ctx.vix_change_pct)} · broker OFF`:'Meta Live todavía no ha generado estado.';
 q('or-meta-live').innerHTML=rows.length?table(['Hora','Activo','Fuente','Estrategia','Lado','Meta','Episodio','Persistencia','Régimen','Razones'],rows.slice().reverse().map(r=>{const reasons=[...(r.block_reasons||[]),...(r.wait_reasons||[])].join(' · ')||'PASS';return `<tr><td>${esc(r.time)}</td><td>${esc(r.symbol)}</td><td>${esc(r.source)}</td><td>${esc(r.strategy)}</td><td>${esc(r.side)}</td><td><strong class="${r.decision==='ACCEPT'?'up':r.decision==='BLOCK'?'down':''}">${esc(r.decision)}</strong></td><td>${esc(r.episode_id)}</td><td>${esc(r.persistence_observations??'—')} obs · ${esc(r.persistence_minutes??'—')}m</td><td>${esc(r.market_regime)}</td><td>${esc(reasons)}</td></tr>`;})):'<p class="muted">Sin decisiones Meta Live para esta selección desde el arranque prospectivo.</p>';
 q('or-episodes').innerHTML=episodes.length?table(['Última obs.','Activo','Fuente','Lado','Episodio','Activaciones','Meta','TTT','Hysteresis','Shadow','Autorizaría 1 entrada'],episodes.slice().reverse().map(r=>`<tr><td>${esc(r.last_observation_at)}</td><td>${esc(r.symbol)}</td><td>${esc(r.source)}</td><td>${esc(r.side)}</td><td>${esc(r.episode_id)}</td><td>${esc((r.activation_times||[]).length)}</td><td>${esc(r.latest_meta_decision)}</td><td>${esc(r.ttt_state)}</td><td>${esc(r.hysteresis_state)}</td><td>${esc(r.shadow_decision)}</td><td>${r.authorization_emitted?'Sí':'No'}</td></tr>`)):'<p class="muted">Sin episodios TTT/Hysteresis todavía. El servicio empezó sin replay histórico.</p>';
}
function render(){
 if(!payload)return;
 const strategies=visibleStrategies(),signals=visibleSignals();
 const matched=signals.filter(r=>r.group==='Coinciden').length,opposed=signals.filter(r=>r.group==='Direcciones opuestas').length;
 const prospectives=payload.live_signals.filter(r=>r.evidence==='PROSPECTIVE').length;
 q('or-stats').innerHTML=[
  ['Señales Options · sesión',payload.live_signals.length],['Coincidencias Jev',matched],['Direcciones opuestas',opposed],['Shadow prospectivo',prospectives]
 ].map(([k,v])=>`<div class="card"><small>${esc(k)}</small><div class="value">${esc(v)}</div></div>`).join('');
 q('or-health').textContent=`${payload.day} · bridge ${payload.version} · read-only · broker actions OFF · actualizado ${payload.generated_at_utc}`;
 renderMetaLive();
 q('or-strategies').innerHTML=table(['Estrategia','Fuente','Evidencia','Lado','Episodios/entradas','Cerradas','Abiertas','Win rate','Retorno medio','TP10 antes SL10','P&L'],strategies.map(r=>`<tr>${[
  r.strategy,r.source,r.evidence,r.side,r.episodes??r.entries,r.closed,r.open
 ].map(v=>`<td>${esc(v)}</td>`).join('')}<td>${pct(r.win_rate)}</td><td>${ret(r.mean_return)}</td><td>${pct(r.tp10_before_sl10_rate)}</td><td>${signed(r.pnl)}</td></tr>`));
 const groupNames=['Coinciden','Jev solo','Options solo','Direcciones opuestas','Ambos abstienen','Sin comparar'];
 const groups=groupNames.map(name=>{const rows=signals.filter(r=>r.group===name),closed=rows.filter(r=>r.jev_pnl!=null);return {group:name,signals:rows.length,jev_closed:closed.length,jev_pnl:closed.reduce((a,r)=>a+Number(r.jev_pnl||0),0)}});
 q('or-groups').innerHTML=table(['Grupo','Señales','Jev cerradas','Jev P&L'],groups.map(r=>`<tr><td>${esc(r.group)}</td><td>${r.signals}</td><td>${r.jev_closed}</td><td>${signed(r.jev_pnl)}</td></tr>`));
 const bands=[[0,.60],[.60,.65],[.65,.70],[.70,.75],[.75,.80],[.80,.90],[.90,1.01]].map(([lo,hi])=>{const rows=signals.filter(r=>r.jev_confidence!=null&&Number(r.jev_confidence)>=lo&&Number(r.jev_confidence)<hi),same=rows.filter(r=>r.group==='Coinciden'),opp=rows.filter(r=>r.group==='Direcciones opuestas');return {band:`${Math.round(lo*100)}–${Math.min(100,Math.round(hi*100))}%`,signals:rows.length,coincide:same.length,opposed:opp.length,jev_pnl_when_coincide:same.reduce((a,r)=>a+Number(r.jev_pnl||0),0),jev_pnl_when_opposed:opp.reduce((a,r)=>a+Number(r.jev_pnl||0),0)}});
 q('or-confidence').innerHTML=table(['Confianza Jev','Comparadas','Coinciden','Opuestas','P&L coincide','P&L opuesta'],bands.map(r=>`<tr><td>${esc(r.band)}</td><td>${r.signals}</td><td>${r.coincide}</td><td>${r.opposed}</td><td>${signed(r.jev_pnl_when_coincide)}</td><td>${signed(r.jev_pnl_when_opposed)}</td></tr>`));
 const symbol=q('or-symbol').value;
 q('or-symbols').innerHTML=table(['Activo','CALL discovery','PUT discovery','Señales live','CALL live','PUT live','Win discovery','Retorno medio discovery'],payload.by_symbol.filter(r=>!symbol||r.symbol===symbol).map(r=>`<tr><td><strong>${esc(r.symbol)}</strong></td><td>${r.call_episodes_discovery}</td><td>${r.put_episodes_discovery}</td><td>${r.live_signals}</td><td>${r.live_call}</td><td>${r.live_put}</td><td>${pct(r.win_rate_discovery)}</td><td>${ret(r.mean_return_discovery)}</td></tr>`));
 q('or-signals').innerHTML=signals.length?table(['Hora','Activo','Jev','Conf.','Options','Estrategia','Fuente','Comparación','Resultado','Options P&L'],signals.slice().reverse().map(r=>`<tr><td>${esc(r.time)}</td><td>${esc(r.symbol)}</td><td>${esc(r.jev_side?`${r.jev_side}${r.jev_active?'':' · SKIP'}`:'—')}</td><td>${pct(r.jev_confidence)}</td><td>${esc(r.options_side)}</td><td>${esc(r.options_strategy)}</td><td>${esc(r.options_source)}</td><td>${esc(r.group)}</td><td>${esc(r.result)}</td><td>${signed(r.options_pnl)}</td></tr>`)):'<p class="muted">Sin señales para estos filtros.</p>';
 const h09d=payload.h09.discovery?.by_candidate||{},h09p=payload.h09.prospective?.by_candidate||{};
 const h09ids=[...new Set([...Object.keys(h09d),...Object.keys(h09p)])];
 q('or-h09').innerHTML=table(['Candidato','Evidencia','Episodios','n 60m','Retorno 60m','Win 60m','TP10 antes SL10'],h09ids.flatMap(id=>[
  ['DISCOVERY',h09d[id]],['PROSPECTIVE',h09p[id]]
 ].filter(x=>x[1]).map(([e,v])=>{const m=v.horizons?.['60']||{};return `<tr><td>${esc(id)}</td><td>${e}</td><td>${v.episodes??0}</td><td>${m.n??0}</td><td>${ret(m.mean_return)}</td><td>${pct(m.win_rate)}</td><td>${pct(m.tp10_before_sl10_rate)}</td></tr>`;})));
 const multid=payload.multisymbol.discovery?.by_candidate||{},multip=payload.multisymbol.prospective?.by_candidate||{},candidateSide=Object.fromEntries((payload.multisymbol.candidates||[]).map(c=>[c.id,c.side]));
 const mids=[...new Set([...Object.keys(multid),...Object.keys(multip)])];
 q('or-multi').innerHTML=table(['Candidato','Lado','Evidencia','Episodios','n 30m','Retorno 30m','Win 30m','MFE','MAE','TP10 antes SL10'],mids.flatMap(id=>[
  ['DISCOVERY',multid[id]],['PROSPECTIVE',multip[id]]
 ].filter(x=>x[1]).map(([e,v])=>{const m=v.horizons?.['30']||{};return `<tr><td>${esc(id)}</td><td>${esc(candidateSide[id])}</td><td>${e}</td><td>${v.episodes??0}</td><td>${m.n??0}</td><td>${ret(m.mean_return)}</td><td>${pct(m.win_rate)}</td><td>${ret(m.mean_mfe)}</td><td>${ret(m.mean_mae)}</td><td>${pct(m.tp10_before_sl10_rate)}</td></tr>`;})));
}

async function load(){
 if(!q(ROOT_ID)||q(ROOT_ID).classList.contains('hidden'))return;
 q('or-health').textContent='Actualizando Options Research…';
 const day=q('or-day').value;
 try{
  const url='/api/options-research'+(day?'?day='+encodeURIComponent(day):'');
  const r=await fetch(url,{cache:'no-store'}); const body=await r.json(); if(!r.ok)throw Error(body.error||`HTTP ${r.status}`);
  payload=body;
  if(!q('or-day').value)q('or-day').value=body.day;
  const old=q('or-symbol').value;
  q('or-symbol').innerHTML='<option value="">Todos</option>'+body.symbols.map(s=>`<option>${esc(s)}</option>`).join(''); q('or-symbol').value=body.symbols.includes(old)?old:'';
  render();
 }catch(e){q('or-health').textContent='No se pudo cargar Options Research: '+e.message;}
}

install();
setInterval(()=>{if(q(ROOT_ID)&&!q(ROOT_ID).classList.contains('hidden'))load();},30000);
})();
