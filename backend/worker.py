"""Single small worker process for persisted discovery and lifecycle jobs."""
import time
from backend import runtime


def main():
    runtime.commercial_startup()
    conn=runtime.get_db()
    try:
        conn.execute("UPDATE analysis_credits SET status='failed' WHERE status='reserved'")
        conn.execute("UPDATE jobs SET status='queued',error='',msg='Resuming saved request after worker restart' WHERE status='running' AND payload!=''")
        conn.commit()
    finally:conn.close()
    runtime.start_scheduler()
    try:
        while True:time.sleep(1)
    except KeyboardInterrupt:pass
    finally:
        runtime.__dict__['_COMMERCIAL_READY']=False
        if runtime.scheduler.running:runtime.scheduler.shutdown(wait=False)


if __name__=='__main__':main()
