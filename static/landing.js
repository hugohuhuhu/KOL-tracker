'use strict';
(async()=>{
  const code=location.pathname.startsWith('/p/')?location.pathname.split('/')[2]:'';
  try{
    const response=await fetch('/api/public'+(code?'?code='+encodeURIComponent(code):''));
    const data=await response.json();
    if(!response.ok)throw new Error(data.error);
    document.title=data.title+' · 你的下一場水上冒險';
    document.querySelector('#brand-title').textContent=data.title;
    document.querySelector('#brand-subtitle').textContent=data.subtitle;
    if(data.code){const badge=document.querySelector('#referral-badge');badge.textContent='✳ 夥伴專屬推薦 · '+data.code;badge.hidden=false;}
    const routeCode=data.code||'_direct';
    const labels={facebook:['f','Facebook','追蹤最新活動與樂園消息'],instagram:['◎','Instagram','把陽光與快樂收藏起來'],website:['↗','官方網站','探索樂園設施與入園資訊']};
    for(const platform of ['kkday','klook','facebook','instagram','website']){
      if(!data.platforms.includes(platform))continue;
      const link=document.createElement('a');
      link.href='/go/'+encodeURIComponent(routeCode)+'/'+platform;
      link.target='_blank';link.rel='noopener';
      if(platform==='kkday'||platform==='klook'){
        link.className='booking-link '+platform;
        link.innerHTML=`<strong>${platform==='kkday'?'KKday':'Klook'}</strong><span>預訂你的水上冒險</span><b aria-hidden="true">↗</b>`;
        link.setAttribute('aria-label','透過 '+(platform==='kkday'?'KKday':'Klook')+' 預訂門票（在新分頁開啟）');
        document.querySelector('#booking-links').append(link);
      }else{
        const [icon,title,description]=labels[platform];
        link.className='social-link';
        link.innerHTML=`<span class="social-icon" aria-hidden="true">${icon}</span><div><strong>${title}</strong><small>${description}</small></div><span aria-hidden="true">↗</span>`;
        link.setAttribute('aria-label',title+'（在新分頁開啟）');
        document.querySelector('#social-links').append(link);
      }
    }
    if(!data.platforms.length){document.querySelector('#public-error').textContent='平台連結準備中，請稍後再回來看看。';document.querySelector('#public-error').hidden=false;}
  }catch(error){document.querySelector('#brand-subtitle').textContent='';const el=document.querySelector('#public-error');el.textContent=error.message||'頁面暫時無法載入，請稍後再試。';el.hidden=false;}
})();
