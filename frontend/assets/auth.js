/* Supabase owns login, signup, email confirmation, recovery and session refresh. */
let authMode='register',sbClient=null,sbEnabled=false;
let recoveringPassword=false;
let syncingSession=null;

async function initSupabaseClient(){
  const config=await api('auth/config');
  if(!config.supabase_enabled||!window.supabase)throw new Error('Sign-in is temporarily unavailable. Please contact support.');
  sbEnabled=true;
  sbClient=window.supabase.createClient(config.supabase_url,config.supabase_anon_key,{
    auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}
  });
  sbClient.auth.onAuthStateChange((event,session)=>{
    window.CM_ACCESS_TOKEN=session?.access_token||'';
    if(event==='SIGNED_OUT'){policiesAccepted=false;showScreen('landing');}
    if(event==='PASSWORD_RECOVERY'){
      recoveringPassword=true;openAuthScreen('recovery');
    }
    // Supabase callbacks must return before another Auth method is awaited.
    if(event==='SIGNED_IN'&&!recoveringPassword)queueMicrotask(()=>activateSession(session).catch(showAuthError));
  });
  const {data,error}=await sbClient.auth.getSession();
  if(error)throw error;
  window.CM_ACCESS_TOKEN=data.session?.access_token||'';
  if(data.session&&!recoveringPassword)await activateSession(data.session);
}
function showAuthError(error){$('#auth-err').textContent=error.message||'Could not sign in.';$('#auth-ok').textContent='';}
async function activateSession(session){
  if(!session?.access_token)return;
  window.CM_ACCESS_TOKEN=session.access_token;
  if(syncingSession)return syncingSession;
  syncingSession=(async()=>{
    if(!await checkUser())throw new Error('Your session could not be verified. Please sign in again.');
    await loadWs();openAppDashboard();
  })();
  try{return await syncingSession;}finally{syncingSession=null;}
}
function openAuthScreen(mode){authMode=mode||'register';renderAuthMode();showScreen('auth');}
function toggleAuthMode(){authMode=authMode==='register'?'login':'register';recoveringPassword=false;renderAuthMode();}
function renderAuthMode(){
  const signup=authMode==='register',recovery=authMode==='recovery';
  $('#auth-title').textContent=recovery?'Choose a new password':signup?'Create your account':'Welcome back';
  $('#auth-sub').textContent=recovery?'Update your password securely.':signup?'Add your product and find relevant conversations.':'Sign in to your saved products and matches.';
  $('#auth-name-wrap').hidden=!signup;
  $('#auth-submit-btn').textContent=recovery?'Save new password':signup?'Create account':'Log in';
  $('#auth-toggle-link').textContent=signup?'Already have an account? Log in':'Need an account? Create account';
  $('#auth-err').textContent='';$('#auth-ok').textContent='';
}
async function submitAuthForm(){
  try{
    if(!sbClient)throw new Error('Sign-in is not configured yet.');
    $('#auth-err').textContent='';$('#auth-ok').textContent='Please wait…';
    const email=$('#auth-email').value.trim(),password=$('#auth-pwd').value;
    if(recoveringPassword){
      if(password.length<8)throw new Error('Use at least eight characters.');
      const {error}=await sbClient.auth.updateUser({password});if(error)throw error;
      recoveringPassword=false;$('#auth-ok').textContent='Password updated.';await checkUser();await loadWs();openAppDashboard();return;
    }
    if(!email||!password)throw new Error('Enter your email and password.');
    if(authMode==='register'&&!$('#auth-policy').checked)throw new Error('Read and accept the Terms and Privacy Policy.');
    const response=authMode==='register'
      ?await sbClient.auth.signUp({email,password,options:{emailRedirectTo:window.location.origin,data:{full_name:$('#auth-name').value.trim()}}})
      :await sbClient.auth.signInWithPassword({email,password});
    if(response.error)throw response.error;
    if(response.data.session)await activateSession(response.data.session);
    else $('#auth-ok').textContent='Check your email to confirm your account, then log in.';
  }catch(error){showAuthError(error);}
}
async function signInWithGoogleSupabase(){
  try{
    if(!sbClient)throw new Error('Sign-in is not configured yet.');
    const {error}=await sbClient.auth.signInWithOAuth({provider:'google',options:{redirectTo:window.location.origin}});
    if(error)throw error;
  }catch(error){showAuthError(error);}
}
async function sendMagicLinkUI(){
  try{await api('auth/magic-link',{email:$('#auth-email').value.trim()});$('#auth-ok').textContent='If eligible, a login link has been sent. Check your email.';}
  catch(error){showAuthError(error);}
}
async function sendPasswordResetUI(){
  try{await api('auth/forgot-password',{email:$('#auth-email').value.trim()});$('#auth-ok').textContent='Check your email for password reset instructions.';}
  catch(error){showAuthError(error);}
}
async function resendConfirmationUI(){
  try{await api('auth/resend-confirmation',{email:$('#auth-email').value.trim()});$('#auth-ok').textContent='Check your email for confirmation instructions.';}
  catch(error){showAuthError(error);}
}
async function logout(){
  if(sbClient){
    const {error}=await sbClient.auth.signOut();
    if(error){showAuthError(error);return;}
  }
  window.CM_ACCESS_TOKEN='';policiesAccepted=false;workspacesList=[];
  localStorage.removeItem('cm_token');localStorage.removeItem('sb_access_token');
  $('#user-badge').textContent='Guest';$('#logout-btn').hidden=true;showScreen('landing');
}
async function checkUser(){
  if(!getToken())return false;
  const user=await api('auth/me');
  const name=user.name||'Founder',first=name.split(' ')[0];
  $('#user-badge').textContent=name;$('#user-avatar').textContent=first[0].toUpperCase();
  $('#dash-greeting').textContent='Welcome, '+first;$('#logout-btn').hidden=false;
  return true;
}
