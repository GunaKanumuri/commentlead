"""API request contracts; no infrastructure dependencies."""
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from decimal import Decimal

class Register(BaseModel):
    email: str
    password: str
    name: str = ''

class Login(BaseModel):
    email: str
    password: str

class SupabaseSync(BaseModel):
    access_token: str
    name: str = ''

class SupabaseConfigUpdate(BaseModel):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str = ''

class EmailAction(BaseModel):
    email: str

class FreePreview(BaseModel):
    query: str
    mode: Literal['auto','topic','video']='auto'

class MatchingProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    business_type: str = Field(default='', max_length=120)
    website: str = Field(default='', max_length=1000)
    target_customer: str = Field(min_length=3, max_length=1000)
    problem: str = Field(min_length=5, max_length=1500)
    delivery_scope: Literal['global', 'countries', 'local']
    locations: str = Field(min_length=2, max_length=500)
    languages: str = Field(min_length=2, max_length=300)
    pricing: str = Field(default='', max_length=500)
    competitors: str = Field(default='', max_length=1000)
    exclusions: str = Field(default='', max_length=1000)
    limitations: str = Field(default='', max_length=1000)

class WS(BaseModel):
    profile: MatchingProfile | None = None
    name: str
    pitch: str
    signals: str = ''
    rules: str = 'No links. No emojis spam.'
    blocklist: str = ''

class BlocklistUpdate(BaseModel):
    blocklist: str

class Feedback(BaseModel):
    feedback: str

class Scan(BaseModel):
    workspace_id: int
    urls: list[str]
    per_video: int = 80

class Auto(BaseModel):
    workspace_id: int
    per_video: int = 80
    max_videos: int = 12

class Report(BaseModel):
    channel_url: str
    per_video: int = 120

class Outcome(BaseModel):
    stage: Literal['new', 'contacted', 'responded', 'qualified', 'purchased', 'irrelevant']
    revenue: Decimal = Field(default=Decimal('0'), ge=0, max_digits=12, decimal_places=2)
    currency: Literal['INR', 'USD', 'EUR', 'GBP', 'AUD', 'CAD', 'SGD', 'AED'] = 'INR'
    rejection_reason: str = Field(default='', max_length=1000)

class PilotFeedback(BaseModel):
    would_pay: Literal['yes', 'no', 'undecided']
    notes: str = Field(default='', max_length=2000)

class Status(BaseModel):
    status: str

class Describe(BaseModel):
    name: str = ''
    rough: str

class Onboard(BaseModel):
    profile: MatchingProfile | None = None
    name: str
    about: str = ''
    audience: str = ''
    features: str = ''
    biz_type: str = ''

class Interest(BaseModel):
    plan: str = 'paid'

class PlanChange(BaseModel):
    email: str
    plan: str
