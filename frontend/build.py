"""Create a static frontend artifact using PUBLIC_API_BASE_URL only. No secrets are copied."""
from pathlib import Path
import json,os,shutil

root=Path(__file__).resolve().parent
output=root/'dist'
output.mkdir(exist_ok=True)
shutil.copyfile(root/'index.html',output/'index.html')
shutil.copytree(root/'assets',output/'assets',dirs_exist_ok=True)
url=os.getenv('PUBLIC_API_BASE_URL','').rstrip('/')
if url and not url.startswith(('https://','http://localhost','http://127.0.0.1')):raise ValueError('PUBLIC_API_BASE_URL must be HTTPS or localhost')
(output/'config.js').write_text('window.APP_CONFIG='+json.dumps({'apiBaseUrl':url})+';\n',encoding='utf8')
print('Static frontend built. No server secrets included.')
