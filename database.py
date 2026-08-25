import sqlite3
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from models import Lead
from utils.logger import get_logger
from config import config

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

logger = get_logger("Database")


class Database:
    def __init__(self, db_path: str = None, db_url: str = None):
        self.db_path = db_path or config.DB_PATH
        self.db_url = db_url or config.DATABASE_URL or os.getenv("DATABASE_URL", "")
        self.is_postgres = bool(self.db_url and HAS_PSYCOPG2)

    def get_connection(self):
        if self.is_postgres:
            conn = psycopg2.connect(self.db_url)
            return conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def _execute(self, cursor, sql: str, params: Any = None):
        """Executes query handling placeholder differences between SQLite (?) and Postgres (%s / %(param)s)."""
        if self.is_postgres:
            # Replace sqlite positional '?' with postgres '%s'
            sql_pg = sql.replace("?", "%s")
            # Replace sqlite named ':field' with postgres '%(field)s'
            import re
            sql_pg = re.sub(r':([a-zA-Z0-9_]+)', r'%(\1)s', sql_pg)
            if params is not None:
                cursor.execute(sql_pg, params)
            else:
                cursor.execute(sql_pg)
        else:
            if params is not None:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

    def _fetchall_dict(self, cursor) -> List[Dict[str, Any]]:
        if self.is_postgres:
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        else:
            return [dict(row) for row in cursor.fetchall()]

    def _fetchone_dict(self, cursor) -> Optional[Dict[str, Any]]:
        if self.is_postgres:
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None
        else:
            row = cursor.fetchone()
            return dict(row) if row else None

    def init_db(self) -> None:
        """Creates tables and required indexes if they do not exist."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS leads (
            lead_id VARCHAR(255) PRIMARY KEY,
            business_name TEXT NOT NULL,
            category TEXT,
            city TEXT,
            phone TEXT,
            address TEXT,
            website_url TEXT,
            website_status TEXT,
            email TEXT,
            instagram TEXT,
            facebook TEXT,
            lead_score INTEGER DEFAULT 0,
            quality_score INTEGER DEFAULT 0,
            lead_tier TEXT,
            qualification_reason TEXT,
            demo_url TEXT,
            demo_status TEXT,
            email_message TEXT,
            whatsapp_message TEXT,
            approval_status TEXT DEFAULT 'PENDING',
            email_status TEXT DEFAULT 'NOT_SENT',
            whatsapp_status TEXT DEFAULT 'NOT_SENT',
            source_url TEXT,
            raw_data TEXT,
            status TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            error_log TEXT,
            last_contacted_at TEXT,
            last_followup_at TEXT,
            followup_count INTEGER DEFAULT 0
        );
        """
        create_index_status_sql = "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);"
        create_index_city_sql = "CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city);"

        create_approvals_table_sql = """
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id VARCHAR(255) PRIMARY KEY,
            lead_id VARCHAR(255) NOT NULL,
            business_name TEXT NOT NULL,
            lead_score INTEGER,
            lead_tier TEXT,
            email_message TEXT,
            whatsapp_message TEXT,
            demo_url TEXT,
            website_status TEXT,
            approval_status TEXT DEFAULT 'PENDING_APPROVAL',
            reviewed_at TEXT,
            notes TEXT
        );
        """

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, create_table_sql)
            self._execute(cursor, create_approvals_table_sql)
            self._execute(cursor, create_index_status_sql)
            self._execute(cursor, create_index_city_sql)
            
            # Migration check for SQLite
            if not self.is_postgres:
                cursor.execute("PRAGMA table_info(leads);")
                columns = [column[1] for column in cursor.fetchall()]
                if "quality_score" not in columns:
                    cursor.execute("ALTER TABLE leads ADD COLUMN quality_score INTEGER DEFAULT 0;")
                if "last_contacted_at" not in columns:
                    cursor.execute("ALTER TABLE leads ADD COLUMN last_contacted_at TEXT;")
                if "last_followup_at" not in columns:
                    cursor.execute("ALTER TABLE leads ADD COLUMN last_followup_at TEXT;")
                if "followup_count" not in columns:
                    cursor.execute("ALTER TABLE leads ADD COLUMN followup_count INTEGER DEFAULT 0;")

            # Auto-update missing lead_tier values
            self._execute(cursor, "UPDATE leads SET lead_tier = 'HOT' WHERE (lead_tier IS NULL OR lead_tier = '' OR lead_tier = 'N/A') AND lead_score >= 70;")
            self._execute(cursor, "UPDATE leads SET lead_tier = 'WARM' WHERE (lead_tier IS NULL OR lead_tier = '' OR lead_tier = 'N/A') AND lead_score >= 45 AND lead_score < 70;")
            self._execute(cursor, "UPDATE leads SET lead_tier = 'LOW' WHERE (lead_tier IS NULL OR lead_tier = '' OR lead_tier = 'N/A') AND lead_score < 45;")

            conn.commit()
            db_type = "PostgreSQL (Cloud)" if self.is_postgres else f"SQLite ('{self.db_path}')"
            logger.info(f"Database initialized successfully using {db_type}.")
        finally:
            conn.close()

    def upsert_approval(self, approval_data: Dict[str, Any]) -> bool:
        """Inserts or updates a record in the approvals table."""
        fields = list(approval_data.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join([f":{f}" for f in fields])
        update_assignments = ", ".join([f"{f} = EXCLUDED.{f}" for f in fields if f != "approval_id"])

        sql = f"""
        INSERT INTO approvals ({columns})
        VALUES ({placeholders})
        ON CONFLICT(approval_id) DO UPDATE SET
            {update_assignments};
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql, approval_data)
            conn.commit()
            return True
        finally:
            conn.close()

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Retrieves all approvals with approval_status = 'PENDING_APPROVAL'."""
        sql = "SELECT * FROM approvals WHERE approval_status = 'PENDING_APPROVAL';"
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql)
            return self._fetchall_dict(cursor)
        finally:
            conn.close()

    def upsert_lead(self, lead: Lead) -> bool:
        """Inserts a new lead or updates an existing lead based on lead_id."""
        lead.updated_at = datetime.now(timezone.utc).isoformat()
        lead_dict = lead.to_dict()

        fields = list(lead_dict.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join([f":{f}" for f in fields])
        
        update_assignments = ", ".join([f"{f} = EXCLUDED.{f}" for f in fields if f != "lead_id"])

        sql = f"""
        INSERT INTO leads ({columns})
        VALUES ({placeholders})
        ON CONFLICT(lead_id) DO UPDATE SET
            {update_assignments};
        """

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql, lead_dict)
            conn.commit()
            logger.info(f"Upserted lead: {lead.business_name} (ID: {lead.lead_id}, Status: {lead.status})")
            return True
        finally:
            conn.close()

    def get_lead_by_id(self, lead_id: str) -> Optional[Lead]:
        """Retrieves a lead by its lead_id."""
        sql = "SELECT * FROM leads WHERE lead_id = ?;"
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql, (lead_id,))
            row = self._fetchone_dict(cursor)
            if row:
                return Lead.from_dict(row)
            return None
        finally:
            conn.close()

    def get_leads_by_status(self, status: str) -> List[Lead]:
        """Retrieves leads filtered by status."""
        sql = "SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC;"
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql, (status,))
            rows = self._fetchall_dict(cursor)
            return [Lead.from_dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_leads(self) -> List[Lead]:
        """Retrieves all leads from the database."""
        sql = "SELECT * FROM leads ORDER BY created_at DESC;"
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql)
            rows = self._fetchall_dict(cursor)
            return [Lead.from_dict(r) for r in rows]
        finally:
            conn.close()

    def get_lead_count(self) -> int:
        """Returns total count of leads."""
        sql = "SELECT COUNT(*) FROM leads;"
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql)
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def get_unprocessed_leads_for_stage(self, stage_name: str) -> List[Lead]:
        """
        Returns leads requiring processing for specified pipeline stage.
        """
        stage_map = {
            "WEBSITE_CHECK": "SELECT * FROM leads WHERE status IN ('DISCOVERED', 'ENRICHED');",
            "SCORING": "SELECT * FROM leads WHERE status = 'VERIFIED';",
            "PERSONALIZATION": "SELECT * FROM leads WHERE status = 'QUALIFIED' AND lead_tier IN ('HOT', 'WARM');",
            "DEMO_URL": "SELECT * FROM leads WHERE status = 'PERSONALIZED';",
            "APPROVAL_QUEUE": "SELECT * FROM leads WHERE status = 'DEMO_READY' AND demo_status = 'READY';",
            "OUTREACH": "SELECT * FROM leads WHERE approval_status = 'APPROVED' AND (email_status != 'SENT' OR whatsapp_status != 'SENT');"
        }

        sql = stage_map.get(stage_name.upper())
        if not sql:
            logger.warning(f"Unknown stage name '{stage_name}'. Returning empty list.")
            return []

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            self._execute(cursor, sql)
            rows = self._fetchall_dict(cursor)
            leads = [Lead.from_dict(r) for r in rows]
            logger.info(f"[Pipeline Resume Check] Found {len(leads)} leads needing processing for stage '{stage_name}'.")
            return leads
        finally:
            conn.close()
