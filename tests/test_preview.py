from unittest.mock import patch
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from backend import runtime as core
from backend.preview import discover,assess

PRODUCT={'description':'Creates short videos from scripts with Telugu voice narration.','customer':'Telugu YouTube Shorts creators','constraints':'Prototype only. No free or unlimited generation. No publishing automation.','readiness':'prototype'}
def body(**values):return core.FreePreview(query='Telugu video tools',mode='topic',product=PRODUCT,**values)
def comment(**values):
    return {'id':'c1','vid':'abcdefghijk','author':'Creator','text':'Need a tool for Telugu voice narration in my Shorts. Any recommendations?','title':'Video tools','published_at':'2026-10-26T12:00:00Z',**values}
def match(**values):
    return {'i':0,'buyer_type':'buyer','direct_match':True,'intent':'recommendation','need':'Needs Telugu narration for Shorts','quote':'Telugu voice narration','feature':'Telugu voice narration','reason':'The prototype demonstrates narration in the requested language.','unknowns':['Prototype suitability needs confirmation'],**values}

def test_product_context_is_required_and_bounded():
    with pytest.raises(ValidationError):core.FreePreview(query='AI video')
    with pytest.raises(ValidationError):core.PreviewProduct(description='Too short',customer='Me')

def test_multiple_videos_deduplicated_and_only_evidence_backed_matches_returned():
    videos={'items':[{'id':{'videoId':vid}} for vid in ['abcdefghijk','bcdefghijkl','cdefghijklm','ignored'] ]}
    with patch.object(core,'yt',return_value=videos),patch.object(core,'comments',side_effect=[
        [comment(),comment(id='promo',text='Check out my tool. Subscribe to my channel')],
        [comment(),comment(id='old',published_at='2020-01-01T00:00:00Z')],[]]) as fetch,patch.object(core,'gem',return_value={'results':[match()]}) as ai:
        result=discover(body())
    assert fetch.call_count==3
    assert result['stats']=={'videos_checked':3,'videos_unavailable':0,'comments_read':4,'comments_assessed':1,'matches':1}
    lead=result['leads'][0]
    assert lead['evidence']['quote'] in lead['text']
    assert lead['evidence']['feature'] in PRODUCT['description']
    assert 'early-access' in lead['intent'] and lead['reply']==''
    assert 'Budget unverified' in lead['evidence']['unknowns']
    assert 'Check out my tool' not in ai.call_args.args[0]

@pytest.mark.parametrize('change',[
    {'quote':'Invented customer request'}, {'feature':'automatic publishing'},
    {'buyer_type':'seller'},{'direct_match':False},{'intent':'generic'},
    {'i':True},{'i':999},{'need':''},{'reason':''},{'quote':''}
])
def test_unproven_ai_output_is_dropped(change):
    with patch.object(core,'gem',return_value={'results':[match(**change)]}):
        assert assess(core.PreviewProduct(**PRODUCT),[comment()])==[]

def test_empty_matches_never_fall_back_to_raw_comments():
    with patch.object(core,'yt',return_value={'items':[{'id':{'videoId':'abcdefghijk'}}]}),patch.object(core,'comments',return_value=[comment(text='The app is not free')]),patch.object(core,'gem',return_value={'results':[]}):
        result=discover(body())
    assert result['leads']==[] and result['stats']['comments_assessed']==1
    assert result['message'].startswith('No relevant opportunities found')

def test_provider_failures_and_partial_results_are_not_no_match_claims():
    with patch.object(core,'yt',return_value={'items':[{'id':{'videoId':'abcdefghijk'}}]}),patch.object(core,'comments',side_effect=HTTPException(503,'Source unavailable')):
        with pytest.raises(HTTPException) as exc:discover(body())
    assert exc.value.status_code==503
    with patch.object(core,'yt',return_value={'items':[{'id':{'videoId':v}} for v in ['abcdefghijk','bcdefghijkl']]}),patch.object(core,'comments',side_effect=[HTTPException(503,'Source unavailable'),[]]):
        result=discover(body())
    assert result['partial'] and not result['message'].startswith('No relevant opportunities')

def test_ai_failure_is_reported_instead_of_unassessed_leads():
    with patch.object(core,'yt',return_value={'items':[{'id':{'videoId':'abcdefghijk'}}]}),patch.object(core,'comments',return_value=[comment()]),patch.object(core,'gem',side_effect=HTTPException(503,'AI unavailable')):
        with pytest.raises(HTTPException):discover(body())

@pytest.mark.parametrize('response',[{}, {'results':'bad'}, []])
def test_malformed_ai_output_is_an_error(response):
    with patch.object(core,'gem',return_value=response):
        with pytest.raises(HTTPException) as exc:assess(core.PreviewProduct(**PRODUCT),[comment()])
    assert exc.value.status_code==502

def test_exhausted_ai_quota_is_not_retried_or_disguised_as_no_matches():
    response=type('Response',(),{'status_code':429,'json':lambda self:{'error':{'status':'RESOURCE_EXHAUSTED'}}})()
    with patch.object(core,'begin_api_call',return_value=1),patch.object(core,'complete_api_call'),patch.object(core.httpx,'post',return_value=response) as post,patch.object(core.os,'getenv',side_effect=lambda k,d=None:'configured-test-key' if k=='GEMINI_API_KEY' else d):
        with pytest.raises(HTTPException) as exc:core.gem('test')
    assert exc.value.status_code==429
    assert 'no unassessed comments' in exc.value.detail
    assert post.call_count==1
