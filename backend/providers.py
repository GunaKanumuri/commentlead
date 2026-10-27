"""Providers: focused API/service functions."""
from backend import runtime as core

def clean_json(text: str):
    if not isinstance(text, str):
        return text
    s = text.strip()
    if s.startswith('```'):
        s = core.re.sub('^```(?:json)?\\s*', '', s, flags=core.re.IGNORECASE)
        s = core.re.sub('\\s*```$', '', s)
    s = s.strip()
    try:
        return core.json.loads(s)
    except core.json.JSONDecodeError:
        m = core.re.search('(\\{.*\\}|\\[.*\\])', s, core.re.DOTALL)
        if m:
            try:
                return core.json.loads(m.group(1))
            except core.json.JSONDecodeError:
                pass
        raise ValueError('Invalid JSON response from AI: ' + s[:150])

def yt(path, **p):
    key = core.os.getenv('YOUTUBE_API_KEY') or core.YT
    if not key or key == 'your_youtube_data_api_key':
        raise core.HTTPException(401, 'YouTube API key is not configured')
    p = {k: v for k, v in p.items() if v}
    for attempt in range(3):
        uid = core.begin_api_call('youtube', path)
        try:
            response = core.httpx.get(f'https://www.googleapis.com/youtube/v3/{path}', params={**p, 'key': key}, timeout=20)
        except core.httpx.RequestError:
            core.complete_api_call(uid, 'network_error')
            if attempt < 2:
                core.time.sleep(0.25 * 2 ** attempt)
                continue
            raise core.HTTPException(503, 'YouTube connection failed; try again shortly')
        core.complete_api_call(uid, str(response.status_code))
        if response.status_code == 200:
            return response.json()
        if response.status_code in (408, 500, 502, 503, 504) and attempt < 2:
            core.time.sleep(0.25 * 2 ** attempt)
            continue
        try:
            error = response.json().get('error', {})
        except ValueError:
            error = {}
        reasons = [item.get('reason') for item in error.get('errors', []) if isinstance(item, dict)]
        if any((reason in reasons for reason in ('quotaExceeded', 'dailyLimitExceeded'))) or response.status_code == 429:
            raise core.HTTPException(429, 'YouTube API daily quota exceeded. Quotas reset at midnight Pacific Time.')
        if 'keyInvalid' in reasons or (response.status_code == 400 and 'key' in error.get('message', '').lower()):
            raise core.HTTPException(401, 'Invalid YouTube API key. Verify YOUTUBE_API_KEY.')
        if 'commentsDisabled' in reasons:
            raise core.HTTPException(403, 'YouTube commentsDisabled')
        raise core.HTTPException(response.status_code if response.status_code in (400, 401, 403, 404) else 502, 'YouTube request failed')

def video_ids(url):
    url = (url or '').strip()
    if not url:
        return []
    if core.re.fullmatch('[\\w-]{11}', url):
        return [url]
    m = core.re.search('(?:v=|youtu\\.be/|shorts/|embed/)([\\w-]{11})', url)
    if m:
        return [m.group(1)]
    cid = None
    m = core.re.search('/channel/(UC[\\w-]+)', url)
    if m:
        cid = m.group(1)
    else:
        m = core.re.search('@([\\w.-]+)', url)
        if m:
            items = core.yt('channels', part='id', forHandle='@' + m.group(1)).get('items', [])
            cid = items[0]['id'] if items else None
    if not cid:
        return []
    items = core.yt('playlistItems', part='contentDetails', playlistId='UU' + cid[2:], maxResults=core.VIDEOS_PER_CHANNEL).get('items', [])
    return [i['contentDetails']['videoId'] for i in items if 'contentDetails' in i and 'videoId' in i['contentDetails']]

def comments(vid, limit):
    items = core.yt('videos', part='snippet', id=vid).get('items', [])
    title = items[0]['snippet']['title'] if items else ''
    channel = items[0]['snippet'].get('channelTitle', '') if items else ''
    channel_id = items[0]['snippet'].get('channelId', '') if items else ''
    out, tok = ([], None)
    while len(out) < limit:
        try:
            d = core.yt('commentThreads', part='snippet', videoId=vid, maxResults=min(100, limit - len(out)), order='time', pageToken=tok, textFormat='plainText')
        except core.HTTPException as e:
            detail = str(e.detail).lower()
            if 'commentsdisabled' in detail or 'disabled comments' in detail or (e.status_code == 403 and 'comment' in detail):
                break
            raise
        for i in d.get('items', []):
            s = i.get('snippet', {}).get('topLevelComment', {}).get('snippet', {})
            out.append(dict(id=i.get('snippet', {}).get('topLevelComment', {}).get('id') or i.get('id', ''), published_at=core.source_date(s.get('publishedAt')), source_updated_at=core.source_date(s.get('updatedAt')), vid=vid, title=title, channel=channel, cid=channel_id, author=s.get('authorDisplayName', ''), text=s.get('textDisplay', '')))
        tok = d.get('nextPageToken')
        if not tok:
            break
    return out[:limit]

def sieve(c):
    text = (c.get('text') or '').strip()
    if not core.re.search('[^\\W\\d_]', text, core.re.UNICODE):
        return False
    words = core.re.findall('\\w+', text)
    noise = '(?:nice|great|good|super|awesome|amazing|first|thanks|thank you|wow|love it)(?:\\s+(?:video|bro|sir|content|explanation|so much))?[!. ]*'
    if core.re.fullmatch(noise, text, core.re.I):
        return False
    return bool(words)

def gem(prompt):
    key = core.os.getenv('GEMINI_API_KEY') or core.GM
    if not key or key == 'your_gemini_api_key':
        raise core.HTTPException(401, 'Gemini API key is not configured')
    models = list(dict.fromkeys([core.os.getenv('GEMINI_MODEL', core.MODEL)] + [x.strip() for x in core.os.getenv('GEMINI_FALLBACK_MODELS', '').split(',') if x.strip()]))
    for model in models:
        for attempt in range(3):
            uid = core.begin_api_call('gemini', model)
            try:
                response = core.httpx.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', params={'key': key}, timeout=45, json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.3}})
            except core.httpx.RequestError:
                core.complete_api_call(uid, 'network_error')
                if attempt < 2:
                    core.time.sleep(0.25 * 2 ** attempt)
                    continue
                raise core.HTTPException(503, 'AI connection failed; your comments can be retried')
            try:
                data = response.json()
            except ValueError:
                data = {}
            core.complete_api_call(uid, str(response.status_code), data.get('usageMetadata'), model)
            if response.status_code == 200:
                try:
                    return core.clean_json(data['candidates'][0]['content']['parts'][0]['text'])
                except (KeyError, IndexError, TypeError, ValueError):
                    raise core.HTTPException(502, 'AI returned an unusable response; saved comments can be retried')
            if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < 2:
                core.time.sleep(0.25 * 2 ** attempt)
                continue
            if response.status_code in (400, 401, 403):
                raise core.HTTPException(503, 'AI request rejected; verify the API key, model access and billing')
            break
    raise core.HTTPException(502, 'AI service unavailable; retry later or check the configured model')
