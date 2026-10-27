const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function context(){
  const nodes=new Map();
  const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:'',textContent:'',hidden:false,checked:false});return nodes.get(selector);};
  const scope=vm.createContext({window:{APP_CONFIG:{apiBaseUrl:'https://api.example.test'},location:{origin:'https://frontend.example.test'}},
    document:{querySelector:node,querySelectorAll:()=>[]},localStorage:{getItem:()=> 'old-local-token',removeItem:()=>{}},
    queueMicrotask,console,fetch:async()=>({ok:true,json:async()=>({})})});
  vm.runInContext(fs.readFileSync('frontend/assets/api.js','utf8'),scope);
  vm.runInContext(fs.readFileSync('frontend/assets/auth.js','utf8'),scope);
  return {scope,node};
}
test('API targets configured backend and never uses an old custom login token',async()=>{
  const {scope}=context();let request;
  scope.fetch=async(url,options)=>{request={url,options};return {ok:true,json:async()=>({ok:true})};};
  await vm.runInContext("api('pricing')",scope);
  assert.equal(request.url,'https://api.example.test/api/pricing');assert.equal(request.options.credentials,'include');
  assert.equal(request.options.headers.Authorization,undefined);
  scope.window.CM_ACCESS_TOKEN='supabase-session';await vm.runInContext("api('workspaces')",scope);
  assert.equal(request.options.headers.Authorization,'Bearer supabase-session');
});
test('Supabase session refresh updates the bearer token and signout clears it',async()=>{
  const {scope}=context();let callback;
  scope.fetch=async()=>({ok:true,json:async()=>({supabase_enabled:true,supabase_url:'https://project.supabase.co',supabase_anon_key:'public-key'})});
  scope.window.supabase={createClient:(url,key)=>{
    assert.equal(key,'public-key');return {auth:{onAuthStateChange:fn=>{callback=fn;},getSession:async()=>({data:{session:null}})}};
  }};
  await vm.runInContext('initSupabaseClient()',scope);
  callback('TOKEN_REFRESHED',{access_token:'refreshed-supabase-token'});
  assert.equal(scope.window.CM_ACCESS_TOKEN,'refreshed-supabase-token');
  vm.runInContext('function showScreen(){}',scope);callback('SIGNED_OUT',null);
  assert.equal(scope.window.CM_ACCESS_TOKEN,'');
});
test('Signup requires policy acceptance and keeps password handling in Supabase',async()=>{
  const {scope,node}=context();let signup;
  node('#auth-email').value='test@example.test';node('#auth-pwd').value='test-password';node('#auth-name').value='Test';
  scope.client={auth:{signUp:async body=>{signup=body;return {data:{session:null}};}}};
  vm.runInContext('sbClient=client;',scope);
  await vm.runInContext('submitAuthForm()',scope);assert.equal(signup,undefined);
  node('#auth-policy').checked=true;await vm.runInContext('submitAuthForm()',scope);
  assert.equal(signup.email,'test@example.test');assert.equal(signup.options.emailRedirectTo,'https://frontend.example.test');
  assert.match(node('#auth-ok').textContent,/confirm your account/);
});
test('Signout clears the active Supabase token only after successful signout',async()=>{
  const {scope}=context();scope.window.CM_ACCESS_TOKEN='active-session';
  vm.runInContext('let workspacesList=[];function showScreen(){}',scope);
  scope.client={auth:{signOut:async()=>({error:new Error('Try again')})}};
  vm.runInContext('sbClient=client;',scope);await vm.runInContext('logout()',scope);
  assert.equal(scope.window.CM_ACCESS_TOKEN,'active-session');
  scope.client.auth.signOut=async()=>({error:null});await vm.runInContext('logout()',scope);
  assert.equal(scope.window.CM_ACCESS_TOKEN,'');
});
