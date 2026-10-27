"""Legacy regressions are explicitly isolated from the application Supabase database."""
import os
from pathlib import Path
os.environ['DATA_BACKEND']='sqlite'
os.environ['APP_ENV']='test'
os.environ['ALLOW_TEST_SQLITE']='true'
os.environ['JOB_EXECUTION_MODE']='inline'
os.environ['PUBLIC_LAUNCH_MODE']='full'
Path('.pytest_cache').mkdir(exist_ok=True)
os.environ['DB_PATH']=str(Path('.pytest_cache')/'test-import-bootstrap.db')
