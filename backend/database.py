"""Supabase Postgres connections. SQLite is available only to isolated legacy tests.

The small DB-API adapter preserves parameterized domain queries during the split.
Production never falls back to a local database after a Supabase connection error.
"""
import os
import re
from collections.abc import Mapping

SCHEMA='app_private'
IDENTITY_TABLES={'users','workspaces','leads','jobs','runs','upgrade_interest','email_logs','api_usage','lead_outcome_events'}


def is_postgres():
    return os.getenv('DATA_BACKEND','supabase')=='supabase'


class Row(Mapping):
    def __init__(self,columns,values):self.columns=columns;self.values=values
    def __getitem__(self,key):return self.values[key] if isinstance(key,int) else self.values[self.columns.index(key)]
    def __iter__(self):return iter(self.columns)
    def __len__(self):return len(self.columns)


def row_factory(cursor):
    columns=[column.name for column in (cursor.description or [])]
    return lambda values:Row(columns,values)


def parameters(sql):
    """Convert qmark parameters without touching question marks in SQL literals."""
    result=[];quoted=False;index=0
    while index<len(sql):
        char=sql[index]
        if char=="'":
            if quoted and index+1<len(sql) and sql[index+1]=="'":
                result.append("''");index+=2;continue
            quoted=not quoted
        result.append('%s' if char=='?' and not quoted else '%%' if char=='%' else char)
        index+=1
    return ''.join(result)


class Cursor:
    def __init__(self,cursor,lastrowid=None):self.cursor=cursor;self.lastrowid=lastrowid
    @property
    def rowcount(self):return self.cursor.rowcount
    def fetchone(self):return self.cursor.fetchone()
    def fetchall(self):return self.cursor.fetchall()
    def __iter__(self):return iter(self.cursor)


class Connection:
    def __init__(self,connection):self.connection=connection
    @property
    def in_transaction(self):
        from psycopg.pq import TransactionStatus
        return self.connection.info.transaction_status!=TransactionStatus.IDLE
    def execute(self,sql,args=()):
        if sql.strip().upper()=='BEGIN IMMEDIATE':
            # Serialize short entitlement/quota mutations across API and worker processes.
            # Transaction-scoped locks also work with Supabase's transaction pooler.
            return Cursor(self.connection.execute('SELECT pg_advisory_xact_lock(731942001)'))
        ignore=bool(re.match(r'\s*INSERT OR IGNORE',sql,re.I))
        replace=bool(re.match(r'\s*INSERT OR REPLACE',sql,re.I))
        sql=re.sub(r'INSERT OR (IGNORE|REPLACE)','INSERT',sql,flags=re.I)
        if ignore:sql+=' ON CONFLICT DO NOTHING'
        if replace:
            if 'policy_acceptance' in sql:sql+=' ON CONFLICT(user_id,version) DO UPDATE SET accepted_at=excluded.accepted_at'
            elif 'lifecycle_cleanup_tasks' in sql:sql+=' ON CONFLICT(task) DO UPDATE SET updated_at=excluded.updated_at,error=excluded.error'
            else:raise ValueError('Unsupported replace statement')
        match=re.match(r'\s*INSERT\s+INTO\s+(\w+)',sql,re.I)
        identity=match and match[1] in IDENTITY_TABLES and 'RETURNING' not in sql.upper()
        if identity:sql+=' RETURNING id'
        cursor=self.connection.execute(parameters(sql),args)
        identifier=None
        if identity:
            row=cursor.fetchone();identifier=row[0] if row else None
        return Cursor(cursor,identifier)
    def executemany(self,sql,rows):
        for row in rows:self.execute(sql,row)
    def commit(self):self.connection.commit()
    def rollback(self):self.connection.rollback()
    def close(self):self.connection.close()


def connect(sqlite_path=None):
    if not is_postgres():
        if os.getenv('APP_ENV')=='production' or os.getenv('ALLOW_TEST_SQLITE')!='true':raise RuntimeError('SQLite is restricted to isolated tests; use Supabase for the application')
        import sqlite3
        connection=sqlite3.connect(sqlite_path,check_same_thread=False,timeout=30)
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA secure_delete=ON')
        return connection
    import psycopg
    url=os.getenv('SUPABASE_DB_URL') or os.getenv('DATABASE_URL')
    if not url:raise RuntimeError('SUPABASE_DB_URL is required; the API secret is not a database password')
    try:
        connection=psycopg.connect(url,connect_timeout=8,prepare_threshold=None,row_factory=row_factory,
            sslmode=os.getenv('PGSSLMODE','require'))
        connection.execute('SELECT set_config(\'search_path\', %s, false)',(SCHEMA+',pg_catalog',))
        connection.commit()
        return Connection(connection)
    except psycopg.Error:
        raise RuntimeError('Cannot connect to Supabase Postgres. Check SUPABASE_DB_URL and the database password.') from None


def verify_schema():
    connection=connect()
    try:
        result=connection.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
        if not result or result[0]!=1:raise RuntimeError('Apply supabase/migrations/202610270001_app_database.sql first')
    finally:connection.close()
