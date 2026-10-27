/* Public preview + waitlist. No account, session, checkout or authentication SDK. */
const POLICY_VERSION='2026-10-27';
const $=selector=>document.querySelector(selector);
const esc=value=>String(value==null?'':value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function serviceUrl(path){return (window.APP_CONFIG?.apiBaseUrl||'').replace(/\/$/,'')+path;}
function apiUrl(path){return serviceUrl('/api/'+path);}
async function api(path,body){
  if(path==='free-preview')await ensurePublicPolicies();
  const response=await fetch(apiUrl(path),{method:body===undefined?'GET':'POST',credentials:'include',
    headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  let result;try{result=await response.json();}catch{throw new Error('This service is temporarily unavailable. Please try again later.');}
  if(!response.ok){
    if(response.status===503||response.status>=500)throw new Error('This service is temporarily unavailable. Please try again later.');
    if(response.status===429)throw new Error('This service is busy right now. Please try again later.');
    throw new Error(typeof result.detail==='string'?result.detail:'Please check the details and try again.');
  }
  return result;
}
document.querySelectorAll('a[href="/privacy"],a[href="/terms"]').forEach(link=>{link.href=serviceUrl(link.getAttribute('href'));});
