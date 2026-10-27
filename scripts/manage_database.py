"""Check/apply the Supabase schema and import a read-only legacy SQLite snapshot.

Run from the project root: python -m scripts.manage_database --check
An import is atomic, rejects conflicting identities, and never deletes the source file.
"""
import argparse,json,os,sqlite3
from pathlib import Path
from dotenv import load_dotenv
from backend import database

ROOT=Path(__file__).resolve().parent.parent
MIGRATION=ROOT/'supabase/migrations/202610270001_app_database.sql'
JSON_COLUMNS={('workspaces','profile'),('workspaces','pilot_feedback'),('leads','evidence')}


def apply_schema():
    connection=database.connect()
    try:connection.connection.execute(MIGRATION.read_text(encoding='utf8'));connection.commit()
    finally:connection.close()


def import_sqlite(path):
    from psycopg import sql
    from psycopg.types.json import Jsonb
    source=Path(path).resolve()
    if not source.is_file():raise RuntimeError('Legacy database file does not exist')
    local=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);local.row_factory=sqlite3.Row
    target=database.connect();counts={}
    try:
        target.execute('BEGIN IMMEDIATE')
        tables=[row[0] for row in local.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        allowed={row[0] for row in target.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='app_private'")}
        for table in tables:
            if table not in allowed:raise RuntimeError('Apply the complete schema before importing: '+table)
            remote_columns={row[0] for row in target.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='app_private' AND table_name=?",(table,))}
            rows=local.execute('SELECT * FROM "'+table+'"').fetchall()
            for row in rows:
                data=dict(row)
                if set(data)-remote_columns:raise RuntimeError('Missing destination columns in '+table)
                # Import only into an empty private application database: never overwrite a customer.
                # A failed/partial import rolls back, so retries remain safe.
                columns=list(data)
                if table=='users':data['password_hash']=''  # Supabase is the only password authority
                for column in columns:
                    if (table,column) in JSON_COLUMNS:
                        value=data[column] or '{}'
                        data[column]=Jsonb(json.loads(value) if isinstance(value,str) else value)
                query=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier('app_private',table),
                    sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns))
                target.connection.execute(query,[data[column] for column in columns])
            counts[table]=len(rows)
        # Identity counters must advance past preserved IDs.
        for table in database.IDENTITY_TABLES:
            target.connection.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'),COALESCE((SELECT MAX(id) FROM {}),1),(SELECT COUNT(*)>0 FROM {}))").format(sql.Identifier('app_private',table),sql.Identifier('app_private',table)),('app_private.'+table,))
        target.commit()
        return counts
    except Exception:
        target.rollback();raise
    finally:local.close();target.close()


def main():
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--check',action='store_true');choice.add_argument('--apply',action='store_true')
    choice.add_argument('--import-sqlite',metavar='PATH')
    args=parser.parse_args()
    os.environ['DATA_BACKEND']='supabase'
    try:
        if args.apply:apply_schema();print('Private Supabase application schema applied.')
        elif args.import_sqlite:
            database.verify_schema()
            connection=database.connect()
            try:
                occupied=sum(connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in database.IDENTITY_TABLES)
                if occupied:raise RuntimeError('Destination is not empty. Import refused to protect existing Supabase data.')
            finally:connection.close()
            counts=import_sqlite(args.import_sqlite);print('Imported counts:',json.dumps(counts,sort_keys=True))
        else:database.verify_schema();print('Supabase connection and complete application schema verified.')
    except Exception as exc:
        # Never print driver exceptions containing connection strings, row data or credentials.
        print('Database operation failed:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__+'. No partial import was committed.')
        raise SystemExit(1)


if __name__=='__main__':main()
