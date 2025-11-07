"""
启动时数据库修复：为 Supplier 表补齐缺失的 code 列并回填

零停机/幂等：重复执行不会报错；在列存在时跳过；在索引存在时跳过
"""
from __future__ import annotations

import random
import string
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError

from fastapi_app.core import database as db_core
from loguru import logger


def _random_code(length: int = 12) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choices(alphabet, k=length))


def _column_exists(conn: Connection, table: str, column: str) -> bool:
    sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table AND column_name = :column
        """
    )
    row = conn.execute(sql, {"table": table, "column": column}).fetchone()
    return row is not None


def _index_exists(conn: Connection, index_name: str) -> bool:
    sql = text(
        """
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = :index_name
        """
    )
    row = conn.execute(sql, {"index_name": index_name}).fetchone()
    return row is not None


def _add_column_if_missing(conn: Connection, table: str, ddl: str) -> None:
    try:
        conn.execute(text(ddl))
    except ProgrammingError as e:
        # 列已存在等情况，忽略
        logger.debug(f"Skip DDL due to ProgrammingError: {e}")


def _create_index_if_missing(conn: Connection, ddl: str) -> None:
    try:
        conn.execute(text(ddl))
    except ProgrammingError as e:
        # 索引已存在等情况，忽略
        logger.debug(f"Skip index DDL due to ProgrammingError: {e}")


def ensure_supplier_code_column_and_backfill() -> None:
    """
    确保 master_data_suppliers.code 列存在；若不存在则添加。
    然后为为 NULL/空的记录回填随机 code，并创建索引。
    幂等可重复执行。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip supplier code fix")
        return

    with db_core.engine.begin() as conn:
        table = 'master_data_suppliers'
        column = 'code'

        # 1) 加列（如不存在）
        if not _column_exists(conn, table, column):
            logger.info("[StartupFix] Adding column master_data_suppliers.code VARCHAR(100)")
            _add_column_if_missing(conn, table, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} VARCHAR(100);")
        else:
            logger.debug("[StartupFix] Column master_data_suppliers.code already exists")

        # 2) 回填空值
        # 2.1) 先回填缺失/空字符串的记录
        update_sql = text(
            """
            UPDATE master_data_suppliers AS t
            SET code = tmp.code
            FROM (
                SELECT id, md5(random()::text || clock_timestamp()::text)::text AS code
                FROM master_data_suppliers
                WHERE (code IS NULL OR code = '')
            ) AS tmp
            WHERE t.id = tmp.id
            """
        )
        affected = conn.execute(update_sql).rowcount
        if affected:
            logger.info(f"[StartupFix] Backfilled code for {affected} suppliers")

        # 3) 创建索引（若缺失）
        if not _index_exists(conn, 'idx_master_data_suppliers_code'):
            logger.info("[StartupFix] Creating index idx_master_data_suppliers_code on code")
            _create_index_if_missing(conn, "CREATE INDEX IF NOT EXISTS idx_master_data_suppliers_code ON master_data_suppliers (code);")
        else:
            logger.debug("[StartupFix] Index idx_master_data_suppliers_code already exists")

        logger.info("[StartupFix] Supplier code column ensured and backfilled")


def ensure_product_bnr_pv_columns() -> None:
    """
    确保 master_data_products 表存在 bnr、pv 两个字段，若不存在则添加。
    幂等，可重复执行。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip product bnr/pv fix")
        return

    with db_core.engine.begin() as conn:
        table = 'master_data_products'
        for col, ddl in (
            ('bnr', f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS bnr VARCHAR(100);"),
            ('pv', f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS pv VARCHAR(100);"),
        ):
            if not _column_exists(conn, table, col):
                logger.info(f"[StartupFix] Adding column {table}.{col} VARCHAR(100)")
                _add_column_if_missing(conn, table, ddl)
            else:
                logger.debug(f"[StartupFix] Column {table}.{col} already exists")


def ensure_inspection_item_alias_column() -> None:
    """
    确保 master_data_inspection_items 表存在 alias 字段。
    幂等，可重复执行。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip inspection_item alias fix")
        return

    with db_core.engine.begin() as conn:
        table = 'master_data_inspection_items'
        col = 'alias'
        if not _column_exists(conn, table, col):
            logger.info(f"[StartupFix] Adding column {table}.{col} VARCHAR(100)")
            _add_column_if_missing(conn, table, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} VARCHAR(100);")
        else:
            logger.debug(f"[StartupFix] Column {table}.{col} already exists")


def ensure_employee_extra_columns() -> None:
    """
    确保 master_data_employees 表存在 join_date, end_date, location, user_type 新列。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip employee extra columns fix")
        return

    with db_core.engine.begin() as conn:
        table = 'master_data_employees'
        columns = [
            ('join_date', f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS join_date DATE;"),
            ('end_date', f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS end_date DATE;"),
            ('location', f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS location VARCHAR(100);"),
            ('user_type', f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_type VARCHAR(20);"),
        ]
        for col, ddl in columns:
            if not _column_exists(conn, table, col):
                logger.info(f"[StartupFix] Adding column {table}.{col}")
                _add_column_if_missing(conn, table, ddl)
            else:
                logger.debug(f"[StartupFix] Column {table}.{col} already exists")


def ensure_organization_manager_column() -> None:
    """
    确保 master_data_organizations 表存在 manager_id 列。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip organization manager_id fix")
        return

    with db_core.engine.begin() as conn:
        table = 'master_data_organizations'
        col = 'manager_id'
        if not _column_exists(conn, table, col):
            logger.info(f"[StartupFix] Adding column {table}.{col} VARCHAR(36)")
            _add_column_if_missing(conn, table, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} VARCHAR(36);")
        else:
            logger.debug(f"[StartupFix] Column {table}.{col} already exists")


def ensure_product_inspection_items_result_inspection_type_column() -> None:
    """
    确保 product_inspection_items_result 表存在 inspection_type 字段。
    用于区分正常检测项和疑似检测项。
    幂等，可重复执行。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip product_inspection_items_result inspection_type fix")
        return

    with db_core.engine.begin() as conn:
        table = 'product_inspection_items_result'
        col = 'inspection_type'

        # 1) 添加列（如不存在）
        if not _column_exists(conn, table, col):
            logger.info(f"[StartupFix] Adding column {table}.{col} VARCHAR(20) with default 'normal'")
            _add_column_if_missing(conn, table,
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} VARCHAR(20) NOT NULL DEFAULT 'normal';")

            # 添加字段注释
            try:
                conn.execute(text(f"COMMENT ON COLUMN {table}.{col} IS '检测项类型：normal(正常检测项) 或 suspected(疑似检测项)';"))
                logger.info(f"[StartupFix] Added comment for column {table}.{col}")
            except ProgrammingError as e:
                logger.debug(f"Skip comment DDL due to ProgrammingError: {e}")
        else:
            logger.debug(f"[StartupFix] Column {table}.{col} already exists")

        logger.info("[StartupFix] Product inspection items result inspection_type column ensured")


def ensure_accounts_table_column() -> None:
    """
    确保 accounts 表的结构符合最新要求：
    1. 添加 config 字段 (JSONB, '个人配置')。
    2. 删除已废弃的 table_column_controls 字段。
    此操作是幂等的，可重复安全执行。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip accounts table fix")
        return

    with db_core.engine.begin() as conn:
        table = 'accounts'

        # 1. 删除已废弃的 'table_column_controls' 字段
        # 使用前置检查，仅在字段存在时才执行删除操作
        col_to_drop = 'table_column_controls'
        if _column_exists(conn, table, col_to_drop):
            logger.info(f"[StartupFix] Dropping deprecated column {table}.{col_to_drop}")
            try:
                # 使用 'IF EXISTS' 是一种更安全的 DDL 写法
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS {col_to_drop};'))
                logger.info(f"[StartupFix] Column {table}.{col_to_drop} dropped successfully")
            except ProgrammingError as e:
                # 捕获异常以防并发等意外情况，确保启动流程的健壮性
                logger.error(f"[StartupFix] Failed to drop column {col_to_drop}: {e}")
        else:
            logger.debug(f"[StartupFix] Column {table}.{col_to_drop} does not exist, skipping drop")

        # 2. 添加新的 'config' 字段
        col_to_add = 'config'
        if not _column_exists(conn, table, col_to_add):
            logger.info(f"[StartupFix] Adding column {table}.{col_to_add} JSONB")
            # 使用辅助函数来添加列，它内部包含了异常处理
            _add_column_if_missing(conn, table, f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {col_to_add} JSONB;')

            # 2.1 添加字段注释
            try:
                comment_sql = f"COMMENT ON COLUMN {table}.{col_to_add} IS '个人配置';"
                conn.execute(text(comment_sql))
                logger.info(f"[StartupFix] Added comment for column {table}.{col_to_add}")
            except ProgrammingError as e:
                logger.debug(f"Skip comment DDL for {col_to_add} due to ProgrammingError: {e}")
        else:
            logger.debug(f"[StartupFix] Column {table}.{col_to_add} already exists")

        logger.info("[StartupFix] Accounts table structure ensured.")


def ensure_oqc_document_task_table_column() -> None:
    """
    确保 oqc_document_extraction_tasks 表的结构和数据符合最新要求。

    此函数执行以下操作，确保过程幂等，可重复安全执行：
    1. 数据迁移：将旧的 `status` 枚举值更新为新值。
       - 'padding' -> 'pending'
       - 'processing' -> 'parsing'
       - 'completed' -> 'success'
       - 'failed' -> 'parsing_failed'
    2. 结构更新：
       - 更新 `status` 字段的注释以反映新的枚举值。
       - 添加 `failed_summary` 字段 (TEXT, '处理失败概要')。
       - 添加 `failed_reason` 字段 (TEXT, '处理失败具体原因')。
    """
    if db_core.engine is None:
        logger.warning("[StartupFix] Sync engine not initialized; skip oqc_document_extraction_tasks table fix")
        return

    with db_core.engine.begin() as conn:
        table: str = 'oqc_document_extraction_tasks'

        # 1. 数据迁移：更新 status 字段的旧枚举值
        # 定义新旧状态的映射关系
        status_migration_map: dict[str, str] = {
            'padding': 'pending',
            'processing': 'parsing',
            'completed': 'success',
            'failed': 'parsing_failed',
            'returning_failed': 'return_failed',
            'callback_failed': 'return_failed',
        }

        logger.info(f"[StartupFix] Begin migrating status values for table {table}")
        try:
            for old_status, new_status in status_migration_map.items():
                update_sql = text(
                    f'UPDATE "{table}" SET status = :new_status WHERE status = :old_status'
                )
                result = conn.execute(update_sql, {"new_status": new_status, "old_status": old_status})
                # 记录受影响的行数，便于观察和调试
                if result.rowcount > 0:
                    logger.info(f"[StartupFix] Migrated {result.rowcount} rows from status '{old_status}' to '{new_status}'")
            logger.info(f"[StartupFix] Status values migration completed for table {table}")
        except ProgrammingError as e:
            # 如果出现错误（例如，表不存在），记录并优雅地跳过
            logger.error(f"Failed to migrate status values for table {table} due to ProgrammingError: {e}")
            return  # 如果数据迁移失败，后续操作可能无意义，提前返回

        # 2. 更新 'status' 字段的注释
        try:
            status_col: str = 'status'
            new_comment: str = '处理状态(pending/parsing/parsing_failed/returning/return_failed/success)'
            comment_sql: str = f"COMMENT ON COLUMN {table}.{status_col} IS '{new_comment}';"
            conn.execute(text(comment_sql))
            logger.debug(f"[StartupFix] Ensured comment for column {table}.{status_col}")
        except ProgrammingError as e:
            logger.debug(f"Skip comment DDL for {status_col} due to ProgrammingError: {e}")

        # 3. 循环处理需要添加的新字段
        columns_to_add: list[dict[str, str]] = [
            {
                "name": "failed_summary",
                "type": "TEXT",
                "comment": "处理失败概要",
            },
            {
                "name": "failed_reason",
                "type": "TEXT",
                "comment": "处理失败具体原因",
            }
        ]

        for col_info in columns_to_add:
            col_name = col_info["name"]
            if not _column_exists(conn, table, col_name):
                logger.info(f"[StartupFix] Adding column {table}.{col_name} {col_info['type']}")
                # 使用 IF NOT EXISTS 保证 DDL 操作的幂等性
                alter_sql: str = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {col_name} {col_info["type"]};'
                _add_column_if_missing(conn, table, alter_sql)

                try:
                    comment_sql = f"COMMENT ON COLUMN {table}.{col_name} IS '{col_info['comment']}';"
                    conn.execute(text(comment_sql))
                    logger.info(f"[StartupFix] Added comment for column {table}.{col_name}")
                except ProgrammingError as e:
                    logger.debug(f"Skip comment DDL for {col_name} due to ProgrammingError: {e}")
            else:
                logger.debug(f"[StartupFix] Column {table}.{col_name} already exists")

        logger.info("[StartupFix] OQC document extraction tasks table structure and data ensured.")


def run_all_startup_fixes() -> None:
    """统一执行所有启动修复任务"""
    logger.info("[StartupFix] Running all startup database fixes...")
    # ensure_supplier_code_column_and_backfill()
    # ensure_product_bnr_pv_columns()
    # ensure_inspection_item_alias_column()
    # ensure_employee_extra_columns()
    # ensure_organization_manager_column()
    # ensure_product_inspection_items_result_inspection_type_column()
    # ensure_accounts_table_column()
    ensure_oqc_document_task_table_column()
    logger.info("[StartupFix] All startup database fixes completed.")


__all__ = ['run_all_startup_fixes']