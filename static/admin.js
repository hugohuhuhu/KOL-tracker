'use strict';
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (n) => Number(n || 0).toLocaleString('zh-TW');
const platforms = {facebook:['f','Facebook'],instagram:['◎','Instagram'],website:['↗','官方網站'],kkday:['K','KKday'],klook:['k','Klook']};
let csrf = '', initialized = true, data = null, editing = null, currentView = 'overview', toastTimer, refreshTimer;

async function api(path, body) {
  const response = await fetch(path, {credentials:'same-origin', headers:body ? {'Content-Type':'application/json','X-CSRF-Token':csrf} : {}, ...(body ? {method:'POST',body:JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !path.endsWith('/login')) {
      clearInterval(refreshTimer);
      $('#referral-dialog').close();
      $('#app').hidden = true;
      $('#auth-screen').hidden = false;
    }
    throw new Error(result.error || '暫時無法完成，請稍後再試。');
  }
  return result;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').classList.toggle('error', error);
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => $('#toast').hidden = true, 4500);
}
function periodQuery() {return '?days=' + $('#period').value;}
async function refresh() {
  data = await api('/api/dashboard' + periodQuery());
  $('#stat-visits').textContent = number(data.totals.visits);
  $('#stat-unique').textContent = number(data.totals.unique_visitors);
  $('#stat-clicks').textContent = number(data.totals.clicks);
  $('#stat-active').textContent = number(data.referrals.filter(r => r.active).length);
  $('#referral-period').textContent = '統計期間：' + $('#period').selectedOptions[0].textContent + ' · 台北時間 UTC+8（可在成效總覽切換）';
  drawChart();
  $('#platform-breakdown').innerHTML = Object.entries(platforms).map(([key,[letter,label]]) => {
    const count = data.referrals.reduce((sum,r) => sum+r[key],0);
    return `<div class="platform-row"><span class="platform-letter">${letter}</span><div><strong>${label}</strong><div class="bar"><i></i></div></div><span>${number(count)}</span></div>`;
  }).join('');
  // CSP forbids inline styles; set the dynamic bar widths through the DOM.
  $$('#platform-breakdown .bar i').forEach((bar,index) => {
    const key = Object.keys(platforms)[index];
    const count = data.referrals.reduce((sum,r) => sum+r[key],0);
    bar.style.width = (data.totals.clicks ? count/data.totals.clicks*100 : 0) + '%';
  });
  $('#overview-table').innerHTML = table(data.referrals.slice(0,5), false);
  renderReferrals();
}
function drawChart() {
  if (!data.daily.length) {
    $('#trend-chart').innerHTML = '<div class="chart-empty"><span>≈</span><p>還沒有浪花，第一個分享就從你開始。</p><small>推薦連結有造訪後，趨勢會出現在這裡。</small></div>';
    return;
  }
  const end = new Date(data.today + 'T00:00:00Z');
  const start = data.days === 'all' ? new Date(data.daily[0].day+'T00:00:00Z') : new Date(end.getTime() - (Number(data.days)-1)*86400000);
  const span = Math.max(1, Math.round((end-start)/86400000));
  const max = Math.max(1,...data.daily.flatMap(d=>[d.visits,d.clicks]));
  const w=560,h=170,left=30,right=12,top=12,bottom=26;
  const x = day => left + Math.round((new Date(day+'T00:00:00Z')-start)/86400000)/span*(w-left-right);
  const y = n => h-bottom-(n/max)*(h-top-bottom);
  let grid='';
  for(let i=0;i<4;i++) {const value=Math.ceil(max*i/3); grid+=`<line x1="${left}" x2="${w-right}" y1="${y(value)}" y2="${y(value)}" stroke="#edf2f2"/><text x="0" y="${y(value)+3}" fill="#91a1a2" font-size="8">${value}</text>`;}
  const indexed = new Map(data.daily.map(d=>[d.day,d]));
  const points=[];
  // One point per day, including zero-traffic days.
  for(let day=new Date(start);day<=end;day.setUTCDate(day.getUTCDate()+1)) {const key=day.toISOString().slice(0,10); points.push(indexed.get(key)||{day:key,visits:0,clicks:0});}
  const lines = ['visits','clicks'].map((key,i)=>`<polyline fill="none" stroke="${i ? '#dfad79' : '#148d8c'}" stroke-width="2" stroke-linejoin="round" points="${points.map(d=>`${x(d.day)},${y(d[key])}`).join(' ')}"/>`).join('');
  const dots = data.daily.map(d=>`<circle cx="${x(d.day)}" cy="${y(d.visits)}" r="3" fill="#148d8c"><title>${d.day}：${d.visits} 次造訪，${d.clicks} 次點擊</title></circle>`).join('');
  $('#trend-chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc($('#period').selectedOptions[0].textContent)}每日造訪與點擊趨勢">${grid}${lines}${dots}<text x="${left}" y="${h-5}" fill="#91a1a2" font-size="8">${start.toISOString().slice(5,10)}</text><text x="${w-right}" y="${h-5}" text-anchor="end" fill="#91a1a2" font-size="8">${data.today.slice(5)}</text></svg>`;
}
function table(rows, full) {
  if (!rows.length) {
    const searching = full && ($('#search').value || $('#status-filter').value !== 'all');
    return `<div class="empty-state"><span>↗</span><h3>${searching?'找不到符合條件的推薦碼':'第一位合作夥伴，從這裡開始'}</h3><p>${searching?'試試其他關鍵字或狀態。':'為 KOL 建立專屬推薦連結，開始記錄每次分享的成效。'}</p>${searching?'':'<button class="button subtle" data-create>＋ 建立第一個推薦碼</button>'}</div>`;
  }
  return `<div class="table-scroll"><table><thead><tr><th>KOL / 合作渠道</th><th>推薦碼</th><th>造訪</th><th>不重複訪客</th><th>平台點擊</th><th>狀態</th><th>操作</th></tr></thead><tbody>${rows.map(r=>`<tr><td><div class="kol-cell"><span class="kol-avatar">${esc([...r.name][0])}</span><div><div class="kol-name" title="${esc(r.name)}">${esc(r.name)}</div><small>${esc(r.channel||'未指定渠道')}</small></div></div></td><td><span class="code-pill">${esc(r.code)}</span></td><td>${number(r.visits)}</td><td>${number(r.unique_visitors)}</td><td>${number(r.clicks)}</td><td><span class="status ${r.active?'':'off'}">${r.active?'啟用中':'已停用'}</span></td><td><div class="row-actions"><button data-copy="${esc(r.code)}" aria-label="複製 ${esc(r.name)} 的推薦連結">複製連結</button><button data-edit="${r.id}" aria-label="編輯 ${esc(r.name)}">編輯</button></div></td></tr>`).join('')}</tbody></table></div>`;
}
function renderReferrals() {
  if(!data)return;
  const term=$('#search').value.toLowerCase();
  const status=$('#status-filter').value;
  $('#referral-table').innerHTML=table(data.referrals.filter(r=>(r.name+' '+r.code+' '+r.channel).toLowerCase().includes(term)&&(status==='all'||Boolean(r.active)===(status==='active'))),true);
}
async function switchView(view) {
  currentView=view;
  $$('.view').forEach(el=>el.hidden=el.id!=='view-'+view);
  $$('[data-view]').forEach(el=>{el.classList.toggle('selected',el.dataset.view===view);el.setAttribute('aria-current',el.dataset.view===view?'page':'false');});
  $('#breadcrumb-current').textContent={overview:'成效總覽',referrals:'KOL 推薦碼',settings:'頁面與連結'}[view];
  if(view==='settings') {
    try {const config=await api('/api/settings');for(const [key,value] of Object.entries(config)){const field=$('#settings-form').elements.namedItem(key);if(field)field.value=value;}fbHint();}
    catch(error){toast(error.message,true);}
  }
}
function openReferral(id) {
  const form=$('#referral-form'); form.reset(); editing=id ? data.referrals.find(r=>r.id===Number(id)) : null;
  $('#referral-error').textContent='';
  $('#dialog-title').textContent=editing?'編輯 KOL 推薦碼':'新增 KOL 推薦碼';
  $('#referral-submit').textContent=editing?'儲存變更 ↗':'建立推薦碼 ↗';
  $('#active-label').hidden=!editing;
  form.elements.code.disabled=Boolean(editing);
  if(editing){for(const key of ['name','channel','code','note'])form.elements[key].value=editing[key]; form.elements.active.checked=Boolean(editing.active);}
  $('#referral-dialog').showModal();
}
async function copyLink(code) {
  const link=(data.public_url||location.origin)+'/r/'+code;
  try{await navigator.clipboard.writeText(link);toast('推薦連結已複製，可以分享給 KOL 了。');}
  catch{ $('#copy-value').value=link;$('#copy-dialog').showModal();$('#copy-value').select(); }
}
function fbHint(){const value=$('#settings-form').elements.facebook.value;$('#fb-hint').textContent=value.includes('facebook.com/search')?'目前使用 Facebook 搜尋結果連結；建議改成官方粉絲專頁直連。':'建議使用官方粉絲專頁的直接網址。';}
async function showApp(){ $('#auth-screen').hidden=true;$('#app').hidden=false; await refresh(); clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden&&currentView==='overview')refresh().catch(e=>toast(e.message,true));},60000); }
async function boot(){
  try {const session=await api('/api/session');csrf=session.csrf;initialized=session.initialized;
    if(session.authenticated)return await showApp();
    $('#auth-screen').hidden=false;
    if(!initialized){$('#auth-title').textContent='建立你的管理中心';$('#auth-description').textContent=session.local_setup?'首次使用，請建立唯一的管理員帳號。密碼至少 12 個字元。':'請先在伺服器執行 python3 app.py --create-admin 建立管理員。';$('#auth-submit').textContent='建立管理員 ↗';$('#auth-form').elements.password.autocomplete='new-password';$('#auth-form').elements.password.minLength=12;if(!session.local_setup)$('#auth-submit').disabled=true;}
  }catch(error){$('#auth-screen').hidden=false;$('#auth-error').textContent=error.message;}
}
$('#auth-form').addEventListener('submit',async event=>{event.preventDefault();const button=$('#auth-submit');button.disabled=true;$('#auth-error').textContent='';const body=Object.fromEntries(new FormData(event.currentTarget));try{if(!initialized){await api('/api/setup',body);initialized=true;}const result=await api('/api/login',body);csrf=result.csrf;event.target.reset();await showApp();}catch(error){$('#auth-error').textContent=error.message;}finally{button.disabled=false;}});
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{});location.reload();}catch(error){toast(error.message,true);}});
$$('[data-view]').forEach(el=>el.addEventListener('click',()=>switchView(el.dataset.view)));
$('#see-all').addEventListener('click',()=>switchView('referrals'));
$('#period').addEventListener('change',()=>refresh().catch(e=>toast(e.message,true)));
$('#search').addEventListener('input',renderReferrals);
$('#status-filter').addEventListener('change',renderReferrals);
$$('.export-report').forEach(button=>button.addEventListener('click',()=>{location.href='/api/export'+periodQuery();}));
document.addEventListener('click',event=>{const create=event.target.closest('.create-referral,[data-create]');if(create)openReferral();const edit=event.target.closest('[data-edit]');if(edit)openReferral(edit.dataset.edit);const copy=event.target.closest('[data-copy]');if(copy)copyLink(copy.dataset.copy);});
$$('.close-dialog').forEach(button=>button.addEventListener('click',()=>$('#referral-dialog').close()));
$('#close-copy').addEventListener('click',()=>$('#copy-dialog').close());
$('#referral-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=$('#referral-submit');button.disabled=true;$('#referral-error').textContent='';try{const body=Object.fromEntries(new FormData(form));if(editing)body.active=form.elements.active.checked;await api('/api/referrals'+(editing?'/'+editing.id:''),body);$('#referral-dialog').close();await refresh();toast(editing?'推薦碼資料已更新。':'專屬推薦碼已建立，點「複製連結」即可分享。');}catch(error){$('#referral-error').textContent=error.message;}finally{button.disabled=false;}});
$('#settings-form').elements.facebook.addEventListener('input',fbHint);
$('#settings-form').addEventListener('submit',async event=>{event.preventDefault();const button=event.currentTarget.querySelector('[type="submit"]');button.disabled=true;$('#settings-error').textContent='';try{await api('/api/settings',Object.fromEntries(new FormData(event.currentTarget)));await refresh();toast('品牌頁面與所有推薦連結已同步更新。');}catch(error){$('#settings-error').textContent=error.message;}finally{button.disabled=false;}});
boot();
