'Commercial entitlements, fair execution and billing. No network calls on import.'
import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import httpx
from fastapi import HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Literal
R = {}
LIFECYCLE_LOCK = threading.RLock()
ALERT_LOG_BODY = 'Lead alert notification. Open your dashboard to review current source evidence.'
PUBLIC_PLANS = {'free': dict(label='Free Trial', price_minor=0, searches=2, leads=30, analysis=150, products=1, queries=1, max_videos=2, auto_scan=False), 'starter': dict(label='Starter', price_minor=49900, searches=5, leads=200, analysis=2000, products=1, queries=2, max_videos=5, auto_scan=False), 'pro': dict(label='Boost', price_minor=99900, searches=10, leads=1000, analysis=8000, products=2, queries=2, max_videos=5, auto_scan=True)}
INTERNAL_PLAN = dict(label='Internal', price_minor=0, searches=None, leads=None, analysis=None, products=None, queries=2, max_videos=5, auto_scan=True)
POLICY_VERSION = '2026-10-27'
class Checkout(BaseModel):
    plan: Literal['starter', 'pro']
class Consent(BaseModel):
    version: str
    accepted: bool
class DeleteAccount(BaseModel):
    confirmation: Literal['DELETE MY ACCOUNT']

from backend.entitlements import now, iso, parse, next_month, schema, plan_of, searches_used, remaining_analysis, reserve_analysis, settle_analysis, unlock_top_leads, product_limit, identity_hash, canonical_email, rate_limit, claim_trial, public_catalog, protect_request, require_processing, verified_email
from backend.queue import funding_class, source_hidden_sql, submit_job, work_queue, plan_status
from backend.billing import gateway, apply_subscription, install
from backend.lifecycle import source_visible, queue_source_sync, expire_source, flush_source_sync, refresh_sources, process_deletions, _process_deletions, policy_page, install_lifecycle, database_backup, production_preflight, consent_response
