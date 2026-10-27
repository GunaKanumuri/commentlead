"""Public launch: an anonymous source preview and an opt-in launch waitlist."""
import os,re
from datetime import timedelta
from fastapi import HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict
from backend import runtime as core


def waitlist_mode():
    return os.getenv('PUBLIC_LAUNCH_MODE','waitlist')=='waitlist'


class WaitlistEntry(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email:str=Field(max_length=254,min_length=3)
    name:str=Field(default='',max_length=100)
    interest:str=Field(default='full-product',max_length=80)
    source:str=Field(default='website',max_length=100)
    consent:bool=False
    policy_version:str=Field(max_length=32)
    website:str=Field(default='',max_length=200)  # Honeypot; no real visitor should fill this.


@core.app.post('/api/waitlist')
def join_waitlist(body:WaitlistEntry,request:Request):
    generic={'ok':True,'message':"You're on the list. We'll email you when this is ready."}
    if body.website:return generic
    email=body.email.strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email):raise HTTPException(422,'Enter a valid email address.')
    if not body.consent or body.policy_version!=core.commerce.POLICY_VERSION:
        raise HTTPException(422,'Please agree to receive a launch update and read the Privacy Policy.')
    try:
        core.commerce.rate_limit('public-waitlist',request.client.host if request.client else 'unknown',5,3600)
        conn=core.get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            cutoff=core.commerce.iso(core.commerce.now()-timedelta(days=1))
            if conn.execute('SELECT COUNT(*) FROM waitlist WHERE created_at>=?',(cutoff,)).fetchone()[0]>=200:
                raise HTTPException(429,'Signups are busy right now. Please try again tomorrow.')
            stamp=core.commerce.iso(core.commerce.now())
            conn.execute('''INSERT INTO waitlist(email,name,interest,source,policy_version,consented_at,created_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(email) DO NOTHING''',
                (email,body.name.strip(),body.interest.strip() or 'full-product',body.source.strip() or 'website',body.policy_version,stamp,stamp))
            conn.commit()
        finally:conn.close()
    except HTTPException:raise
    except Exception:
        core.logger.warning('Public waitlist storage unavailable')
        raise HTTPException(503,'Waitlist signups are temporarily unavailable. Please try again later.') from None
    return generic
