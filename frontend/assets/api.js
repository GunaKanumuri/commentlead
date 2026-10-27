/* All product data passes through the Python API. Supabase handles authentication. */
const POLICY_VERSION='2026-10-27';
let policiesAccepted=false;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value==null?'':value).replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));
function getToken(){return window.CM_ACCESS_TOKEN||'';}
function serviceUrl(path){return (window.APP_CONFIG?.apiBaseUrl||'').replace(/\/$/,'')+path;}
function apiUrl(path){return serviceUrl('/api/'+path);}
function authHeaders(){const token=getToken();return token?{Authorization:'Bearer '+token}:{};}
async function api(path,body){
  if(['auto','scan','report','describe'].includes(path)||/workspaces\/\d+\/reassess/.test(path))await ensurePolicies();
  if(path==='free-preview')await ensurePublicPolicies();
  const response=await fetch(apiUrl(path),{
    method:body===undefined?'GET':'POST',credentials:'include',
    headers:{'Content-Type':'application/json',...authHeaders()},
    ...(body===undefined?{}:{body:JSON.stringify(body)})
  });
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Request failed. Please retry.');
  return result;
}
document.querySelectorAll('a[href="/privacy"],a[href="/terms"],a[href="/refunds"]').forEach(link=>{
  link.href=serviceUrl(link.getAttribute('href'));
});
