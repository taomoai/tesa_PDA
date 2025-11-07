"""
PostgreSQL 逻辑复制订阅服务 - 用于操作日志记录
"""
import os
import asyncio
import json
from typing import Dict, Optional, List
from loguru import logger
import asyncpg
from asyncpg.connection import Connection

from fastapi_app.core.config import get_settings
from fastapi_app.core.db_connection_utils import build_asyncpg_connection_params
from fastapi_app.services.logging_service import log_operation
from fastapi_app.core.event_bus import get_event_bus_manager
from fastapi_app.events.database_events import (
    DatabaseOperation,
    create_database_change_event
)


class BinlogSubscriber:
    """PostgreSQL逻辑复制订阅者"""
    
    def __init__(self, auto_discover_tables: bool = True):
        self.connection: Optional[Connection] = None
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.auto_discover_tables = auto_discover_tables

        # 手动配置的表（优先级更高，可以覆盖自动发现的配置）
        self.manual_table_configs = {}

        # 实际监控的表配置（手动配置 + 自动发现）
        self.monitored_tables = {}

    async def _discover_tables(self):
        """自动发现数据库中的所有表"""
        if not self.auto_discover_tables:
            return

        try:
            # 查询所有用户表（排除系统表）
            query = """
                SELECT
                    t.table_name,
                    array_agg(c.column_name ORDER BY c.ordinal_position) as columns,
                    obj_description(pgc.oid, 'pg_class') as table_comment
                FROM information_schema.tables t
                LEFT JOIN information_schema.columns c ON t.table_name = c.table_name
                    AND t.table_schema = c.table_schema
                LEFT JOIN pg_class pgc ON pgc.relname = t.table_name
                WHERE t.table_schema = 'public'
                    AND t.table_type = 'BASE TABLE'
                    AND t.table_name NOT LIKE 'alembic_%'
                    AND t.table_name NOT LIKE '%_pkey'
                    AND t.table_name NOT LIKE '%_seq'
                GROUP BY t.table_name, pgc.oid
                ORDER BY t.table_name
            """

            result = await self.connection.fetch(query)

            for row in result:
                table_name = row['table_name']
                columns = row['columns']
                table_comment = row['table_comment'] or ''

                # 如果已经有手动配置，跳过
                if table_name in self.manual_table_configs:
                    continue

                # 自动生成配置
                module_name = self._generate_module_name(table_name, table_comment)
                fields = self._generate_field_mapping(columns)

                self.monitored_tables[table_name] = {
                    'module': module_name,
                    'fields': fields,
                    'auto_discovered': True,
                    'table_comment': table_comment
                }

                logger.debug(f"[BinlogSubscriber] Table '{table_name}' classified as module '{module_name}' (comment: '{table_comment}')")

            # 统计各模块的表数量
            module_stats = {}
            for table_name, config in self.monitored_tables.items():
                module = config['module']
                if module not in module_stats:
                    module_stats[module] = []
                module_stats[module].append(table_name)

            logger.info(f"[BinlogSubscriber] Auto-discovered {len(self.monitored_tables)} tables for monitoring")
            for module, tables in module_stats.items():
                logger.info(f"[BinlogSubscriber] Module '{module}': {len(tables)} tables - {', '.join(tables)}")

        except Exception as e:
            logger.error(f"[BinlogSubscriber] Failed to discover tables: {e}")

    def _generate_module_name(self, table_name: str, table_comment: str = '') -> str:
        """根据表名和表注释智能生成模块名"""
        # 定义表名到模块的映射规则
        module_mapping = {
            # 主数据模块 (Master Data)
            'master_data_products': 'master_data',
            'master_data_suppliers': 'master_data',
            'master_data_employees': 'master_data',
            'master_data_organizations': 'master_data',
            'master_data_inspection_items': 'master_data',
            'master_data_inspection_standards': 'master_data',
            'product_inspection_items_result': 'master_data',
            'product_extraction_config': 'master_data',
            'tesa_inspection_results': 'master_data',

            # SPC监控模块 (SPC/Monitor) - 基于实际表名
            'monitor_new': 'spc_monitor',  # 实际的监控表名
            'monitor_algorithm_new': 'spc_monitor',
            'monitor_inspection': 'spc_monitor',
            'monitor_event_data_new': 'spc_monitor',
            'monitor_event_result_new': 'spc_monitor',
            'monitor_recommend_data_new': 'spc_monitor',  # 实际表名
            'inspection_algorithm_relation': 'spc_monitor',
            'inspection_algorithm_relation_map': 'spc_monitor',
            'algorithm_new': 'spc_monitor',
            'alarm_new': 'spc_monitor',
            'alarm_data_result_new': 'spc_monitor',
            'control_label': 'spc_monitor', 

            # AI提取任务模块 (AI Extract Task)
            'oqc_document_extraction_tasks': 'ai_extract',

            # 知识库模块 (Knowledge Base)
            'knowledge_graph_base': 'knowledge_base',
            'knowledge_base_info': 'knowledge_base',
            'knowledge_graph_schema': 'knowledge_base',
            'knowledge_source': 'knowledge_base',
            'knowledge_trees': 'knowledge_base',
            'knowledge_items': 'knowledge_base',
            'knowledge_item_tags': 'knowledge_base',

            # 标签模块 (Tag Management)
            'tag_types': 'tag_management',
            'tags': 'tag_management',

            # API模块 (API Management)
            'api_collections': 'api_management',
            'api_items': 'api_management',

            # 数据连接模块 (Data Connection)
            'data_connection': 'data_connection',
            'database_connection': 'data_connection',
            'database_meta': 'data_connection',
            'table_meta': 'data_connection',

            # 代理资源模块 (Agent Resource)
            'agent_resource': 'agent_resource',

            # 分析模块 (Analysis)
            'analysis': 'analysis',
            'analysis_flow_config': 'analysis',
            'analysis_flow': 'analysis',
            'analysis_recommendation': 'analysis',

            # 项目模块 (Project Management)
            'projects': 'project_management',
            'project_data_set': 'project_management',
            'project_data_series': 'project_management',

            # 聊天模块 (Chat/Conversation) - 基于实际表名
            'chat_conversations': 'chat_management',  # 实际表名
            'chat_messages': 'chat_management',  # 实际表名

            # 涂层模块 (Coating)
            'coating_running_params': 'coating_management',
            'coating_databox_values': 'coating_management',

            # LLM模块 (LLM Management)
            'llm_providers': 'llm_management',
            'llm_configs': 'llm_management',
            'llm_call_histories': 'llm_management',

            # 租户模块 (Tenant Management)
            'tenants': 'tenant_management',
        }

        # 首先检查精确匹配
        if table_name in module_mapping:
            return module_mapping[table_name]

        # 如果有表注释，也用于辅助判断
        comment_lower = table_comment.lower() if table_comment else ''

        # 基于表名前缀的模糊匹配
        table_lower = table_name.lower()
        combined_text = f"{table_lower} {comment_lower}"  # 结合表名和注释进行匹配

        # 主数据相关
        if any(keyword in combined_text for keyword in ['master_data', 'product', 'supplier', 'employee', 'organization', 'inspection_item', 'inspection_standard', '主数据', '产品', '供应商', '员工', '组织', '检验项', '检验标准']):
            return 'master_data'

        # SPC监控相关
        if any(keyword in combined_text for keyword in ['monitor', 'spc', 'alarm', 'algorithm', 'event', '监控', '报警', '算法', '事件', '统计过程控制']):
            return 'spc_monitor'

        # AI提取任务相关
        if any(keyword in combined_text for keyword in ['extraction', 'task', 'oqc', 'document', '提取', '任务', '文档', 'ai', '人工智能']):
            return 'ai_extract_task'

        # 知识库相关
        if any(keyword in combined_text for keyword in ['knowledge', 'graph', 'tree', '知识', '图谱', '知识库']):
            return 'knowledge_base'

        # 标签相关
        if any(keyword in combined_text for keyword in ['tag', '标签']):
            return 'tag_management'

        # API相关
        if any(keyword in combined_text for keyword in ['api', '接口']):
            return 'api_management'

        # 数据连接相关
        if any(keyword in combined_text for keyword in ['connection', 'database', 'table_meta', '连接', '数据库', '元数据']):
            return 'data_connection'

        # 分析相关
        if any(keyword in combined_text for keyword in ['analysis', '分析']):
            return 'analysis'

        # 项目相关
        if any(keyword in combined_text for keyword in ['project', '项目']):
            return 'project_management'

        # 聊天相关
        if any(keyword in combined_text for keyword in ['conversation', 'message', 'chat', '对话', '消息', '聊天']):
            return 'chat_management'

        # 涂层相关
        if any(keyword in combined_text for keyword in ['coating', '涂层']):
            return 'coating_management'

        # LLM相关
        if any(keyword in combined_text for keyword in ['llm', '大语言模型', '语言模型']):
            return 'llm_management'

        # 默认情况：基于表名生成通用模块名
        # 移除复数形式，转换为模块名
        if table_name.endswith('ies'):
            base_name = table_name[:-3] + 'y'
        elif table_name.endswith('s'):
            base_name = table_name[:-1]
        else:
            base_name = table_name

        return f"{base_name}_management"

    def _generate_field_mapping(self, columns: List[str]) -> Dict[str, str]:
        """生成字段映射（保持原始字段名）"""
        field_mapping = {}

        # 直接使用原始字段名
        for column in columns:
            field_mapping[column] = column

        return field_mapping

    async def start(self):
        """启动binlog订阅服务"""
        if self.running:
            return

        try:
            # 直接从环境变量读取数据库配置，与Flask保持一致
            db_host = os.getenv('DB_HOST')
            db_port = int(os.getenv('DB_PORT', '5432'))
            db_database = os.getenv('DB_DATABASE') or os.getenv('DB_NAME')
            db_user = os.getenv('DB_USER')
            db_password = os.getenv('DB_PASSWORD')

            # 处理密码：先处理引号，再处理URL编码
            from urllib.parse import unquote_plus

            # 如果密码被双引号包围，去掉引号
            if db_password and db_password.startswith('"') and db_password.endswith('"'):
                clean_password = db_password[1:-1]
                logger.info("[BinlogSubscriber] Removed surrounding quotes from password")
            else:
                clean_password = db_password

            # 处理URL编码的密码（与SQLAlchemy的行为保持一致）
            if clean_password:
                try:
                    decoded_password = unquote_plus(clean_password)
                    if decoded_password != clean_password:
                        clean_password = decoded_password
                        logger.info("[BinlogSubscriber] Detected URL-encoded password, using decoded version")
                except:
                    pass  # 如果解码失败，使用原密码

            if not all([db_host, db_port, db_database, db_user, db_password]):
                # 如果环境变量不完整，回退到FastAPI配置
                logger.warning("[BinlogSubscriber] Environment variables incomplete, falling back to FastAPI config")
                settings = get_settings()
                db_config = settings.database
                connect_kwargs = build_asyncpg_connection_params(
                    db_config,
                    application_name='taomoai_binlog_subscriber'
                )
            else:
                logger.info(f"[BinlogSubscriber] Using environment variables for database connection: {db_host}:{db_port}/{db_database} as {db_user}")
                # 使用环境变量构建连接参数（与Flask一致）
                connect_kwargs = {
                    'host': db_host,
                    'port': db_port,
                    'user': db_user,
                    'password': clean_password,
                    'database': db_database,
                    'server_settings': {
                        'application_name': 'taomoai_binlog_subscriber'
                    }
                }

                # 检查是否为Azure PostgreSQL并添加SSL
                if 'database.chinacloudapi.cn' in db_host or 'database.azure.com' in db_host:
                    connect_kwargs['ssl'] = 'require'
                    logger.info(f"[BinlogSubscriber] Detected Azure PostgreSQL ({db_host}), enabling SSL connection")

                logger.info(f"[BinlogSubscriber] Using environment variables for database connection: {db_host}:{db_port}/{db_database} as {db_user}")

            # 创建专用的数据库连接
            self.connection = await asyncpg.connect(**connect_kwargs)

            # 自动发现表（如果启用）
            await self._discover_tables()

            # 合并手动配置的表（手动配置优先级更高）
            self.monitored_tables.update(self.manual_table_configs)

            logger.info(f"[BinlogSubscriber] Monitoring {len(self.monitored_tables)} tables: {list(self.monitored_tables.keys())}")

            self.running = True
            self.task = asyncio.create_task(self._subscribe_loop())
            logger.info("[BinlogSubscriber] Started successfully")
            
        except Exception as e:
            logger.error(f"[BinlogSubscriber] Failed to start: {e}")

            # 如果是pg_hba.conf错误，提供更详细的错误信息
            if "pg_hba.conf" in str(e):
                logger.error("[BinlogSubscriber] PostgreSQL access control error detected:")
                logger.error("  - Check if the client IP address is allowed in pg_hba.conf")
                logger.error("  - For Azure PostgreSQL, check firewall rules and connection security settings")
                logger.error("  - Consider enabling SSL if connecting to Azure PostgreSQL")
            elif "no encryption" in str(e):
                logger.error("[BinlogSubscriber] SSL/encryption error detected:")
                logger.error("  - Azure PostgreSQL requires SSL connections")
                logger.error("  - Add ssl='require' to connection parameters")

            await self.stop()
    
    async def stop(self):
        """停止binlog订阅服务"""
        if not self.running:
            return

        self.running = False

        # 取消任务（添加超时）
        if self.task:
            self.task.cancel()
            try:
                await asyncio.wait_for(self.task, timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("[BinlogSubscriber] Task timeout (1s), forcing stop")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[BinlogSubscriber] Error stopping task: {e}")

        # 关闭连接（添加超时）
        if self.connection:
            try:
                await asyncio.wait_for(self.connection.close(), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("[BinlogSubscriber] Connection close timeout (1s)")
            except Exception as e:
                logger.error(f"[BinlogSubscriber] Error closing connection: {e}")
            finally:
                self.connection = None

        logger.info("[BinlogSubscriber] Stopped")
    
    async def _subscribe_loop(self):
        """订阅循环 - 使用LISTEN/NOTIFY机制"""
        try:
            # 设置触发器和通知函数（如果不存在）
            await self._setup_triggers()
            
            # 监听通知
            await self.connection.add_listener('table_changes', self._handle_notification)
            
            logger.info("[BinlogSubscriber] Listening for database changes...")
            
            # 保持连接活跃
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"[BinlogSubscriber] Subscribe loop error: {e}")
            if self.running:
                # 重试连接
                await asyncio.sleep(5)
                await self.start()
    
    async def _setup_triggers(self):
        """设置数据库触发器和通知函数"""
        try:
            # 创建通知函数 - 直接在数据库层面计算changes，避免传输完整行数据
            await self.connection.execute("""
                CREATE OR REPLACE FUNCTION notify_table_changes()
                RETURNS TRIGGER AS $$
                DECLARE
                    payload JSON;
                    payload_text TEXT;
                    changes JSON[];
                    change_item JSON;
                    col_name TEXT;
                    old_val TEXT;
                    new_val TEXT;
                    max_payload_size INTEGER := 7500; -- 设置最大载荷大小
                    -- 关键字段变量
                    key_fields TEXT[] := ARRAY['id', 'tenant_id', 'created_by', 'updated_by'];
                    key_field TEXT;
                    key_old_val TEXT;
                    key_new_val TEXT;
                    field_exists BOOLEAN;
                    field_already_in_changes BOOLEAN;
                BEGIN
                    changes := ARRAY[]::JSON[];

                    -- 根据操作类型计算字段变更
                    IF TG_OP = 'DELETE' THEN
                        -- DELETE操作：所有字段都是被删除
                        FOR col_name IN
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = TG_TABLE_NAME
                            AND table_schema = TG_TABLE_SCHEMA
                        LOOP
                            EXECUTE format('SELECT ($1).%I::text', col_name) USING OLD INTO old_val;
                            IF old_val IS NOT NULL THEN
                                change_item := json_build_object(
                                    'field', col_name,
                                    'field_name', col_name,
                                    'old_value', old_val,
                                    'new_value', null,
                                    'change_type', 'REMOVE'
                                );
                                changes := changes || change_item;
                            END IF;
                        END LOOP;

                    ELSIF TG_OP = 'INSERT' THEN
                        -- INSERT操作：所有非空字段都是新增
                        FOR col_name IN
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = TG_TABLE_NAME
                            AND table_schema = TG_TABLE_SCHEMA
                        LOOP
                            EXECUTE format('SELECT ($1).%I::text', col_name) USING NEW INTO new_val;
                            IF new_val IS NOT NULL THEN
                                change_item := json_build_object(
                                    'field', col_name,
                                    'field_name', col_name,
                                    'old_value', null,
                                    'new_value', new_val,
                                    'change_type', 'ADD'
                                );
                                changes := changes || change_item;
                            END IF;
                        END LOOP;

                    ELSIF TG_OP = 'UPDATE' THEN
                        -- UPDATE操作：记录所有字段变更，关键字段即使没有变化也要包含
                        FOR col_name IN
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = TG_TABLE_NAME
                            AND table_schema = TG_TABLE_SCHEMA
                        LOOP
                            EXECUTE format('SELECT ($1).%I::text', col_name) USING OLD INTO old_val;
                            EXECUTE format('SELECT ($1).%I::text', col_name) USING NEW INTO new_val;

                            -- 对于关键字段，即使没有变化也要包含
                            -- 对于其他字段，只有变化时才包含
                            IF col_name = ANY(key_fields) OR (old_val IS DISTINCT FROM new_val) THEN
                                change_item := json_build_object(
                                    'field', col_name,
                                    'field_name', col_name,
                                    'old_value', old_val,
                                    'new_value', new_val,
                                    'change_type', CASE
                                        WHEN old_val IS DISTINCT FROM new_val THEN 'MODIFY'
                                        ELSE 'UNCHANGED'
                                    END
                                );
                                changes := changes || change_item;
                            END IF;
                        END LOOP;
                    END IF;



                    -- 构建最终载荷
                    payload = json_build_object(
                        'operation', TG_OP,
                        'table', TG_TABLE_NAME,
                        'timestamp', extract(epoch from now()),
                        'record_id', CASE
                            WHEN COALESCE(NEW.id, OLD.id) IS NOT NULL THEN COALESCE(NEW.id, OLD.id)::text
                            ELSE NULL
                        END,
                        'changes', array_to_json(changes),
                        'old_data', NULL, -- 不再需要完整行数据
                        'new_data', NULL  -- 不再需要完整行数据
                    );

                    payload_text := payload::text;

                    -- 如果载荷仍然过大，只保留基本信息
                    IF length(payload_text) > max_payload_size THEN
                        payload = json_build_object(
                            'operation', TG_OP,
                            'table', TG_TABLE_NAME,
                            'timestamp', extract(epoch from now()),
                            'record_id', CASE
                                WHEN COALESCE(NEW.id, OLD.id) IS NOT NULL THEN COALESCE(NEW.id, OLD.id)::text
                                ELSE NULL
                            END,
                            'changes', '[]'::json,
                            'message', 'Changes too large for notification'
                        );
                        payload_text := payload::text;
                    END IF;

                    -- 最终安全检查并发送通知
                    IF length(payload_text) <= max_payload_size THEN
                        PERFORM pg_notify('table_changes', payload_text);
                    ELSE
                        -- 记录警告但不阻止操作
                        RAISE WARNING 'Notification payload too large for table %, operation %, record_id %',
                            TG_TABLE_NAME, TG_OP, COALESCE(NEW.id, OLD.id);
                    END IF;

                    RETURN COALESCE(NEW, OLD);
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 为监控的表创建触发器
            for table_name in self.monitored_tables.keys():
                # 确保表名和触发器名正确转义
                escaped_table_name = f'"{table_name}"' if table_name[0].isdigit() or '-' in table_name else table_name
                # 触发器名称需要是有效的标识符，替换特殊字符
                safe_trigger_name = table_name.replace('-', '_').replace('.', '_')
                trigger_name = f'"{safe_trigger_name}_changes_trigger"'

                # 删除旧触发器（如果存在）
                await self.connection.execute(f"""
                    DROP TRIGGER IF EXISTS {trigger_name} ON {escaped_table_name};
                """)

                # 创建新触发器
                await self.connection.execute(f"""
                    CREATE TRIGGER {trigger_name}
                    AFTER INSERT OR UPDATE OR DELETE ON {escaped_table_name}
                    FOR EACH ROW EXECUTE FUNCTION notify_table_changes();
                """)
            
            logger.info("[BinlogSubscriber] Database triggers setup completed")
            
        except Exception as e:
            logger.error(f"[BinlogSubscriber] Failed to setup triggers: {e}")
            raise
    
    async def _handle_notification(self, _connection, _pid, _channel, payload):
        """处理数据库变更通知"""
        try:
            # 解析通知数据
            data = json.loads(payload)
            table_name = data.get('table')
            operation = data.get('operation')
            record_id = data.get('record_id')
            timestamp = data.get('timestamp')
            changes_data = data.get('changes', [])
            message = data.get('message')

            # 检查是否是监控的表
            if table_name not in self.monitored_tables:
                return

            # 如果是载荷过大的消息，记录警告
            if message == 'Changes too large for notification':
                logger.warning(f"[BinlogSubscriber] Changes too large for {operation} on {table_name}, record_id: {record_id}")
                # 即使changes过大，我们也创建一个基本的变更记录
                changes_data = [{
                    'field': 'operation',
                    'field_name': '操作类型',
                    'old_value': None if operation == 'INSERT' else operation,
                    'new_value': operation if operation != 'DELETE' else None,
                    'change_type': 'ADD' if operation == 'INSERT' else
                                  'REMOVE' if operation == 'DELETE' else 'MODIFY'
                }]

            table_config = self.monitored_tables[table_name]

            # 将数据库层面计算的changes转换为FieldChange对象
            changes = []
            if changes_data:
                from fastapi_app.events.database_events import FieldChange, ChangeType

                for change_data in changes_data:
                    try:
                        change = FieldChange(
                            field=change_data.get('field', ''),
                            field_name=change_data.get('field_name', change_data.get('field', '')),
                            old_value=change_data.get('old_value'),
                            new_value=change_data.get('new_value'),
                            change_type=ChangeType(change_data.get('change_type', 'MODIFY'))
                        )
                        changes.append(change)
                    except Exception as change_error:
                        logger.warning(f"[BinlogSubscriber] Failed to parse change data: {change_error}")
                        continue

            # 如果没有解析到任何changes，创建一个基本的操作记录
            if not changes and operation in ['INSERT', 'UPDATE', 'DELETE']:
                from fastapi_app.events.database_events import FieldChange, ChangeType

                change = FieldChange(
                    field='record_id',
                    field_name='记录ID',
                    old_value=record_id if operation in ['UPDATE', 'DELETE'] else None,
                    new_value=record_id if operation in ['INSERT', 'UPDATE'] else None,
                    change_type=ChangeType.ADD if operation == 'INSERT' else
                               ChangeType.REMOVE if operation == 'DELETE' else
                               ChangeType.MODIFY
                )
                changes = [change]

            # 从changes中提取基础字段信息
            extracted_user_id = None
            extracted_tenant_id = None
            extracted_record_id = record_id  # 使用从数据库触发器传来的record_id

            for change in changes:
                field = change.field
                # 提取用户ID
                if field in ['created_by', 'updated_by'] and not extracted_user_id:
                    if operation == 'INSERT' and field == 'created_by':
                        extracted_user_id = change.new_value
                    elif operation in ['UPDATE', 'DELETE'] and field == 'updated_by':
                        extracted_user_id = change.new_value or change.old_value

                # 提取租户ID
                if field == 'tenant_id' and not extracted_tenant_id:
                    extracted_tenant_id = change.new_value or change.old_value

                # 提取记录ID（如果触发器没有提供的话）
                if field == 'id' and not extracted_record_id:
                    extracted_record_id = change.new_value or change.old_value

            # 创建数据库变更事件
            event = create_database_change_event(
                table_name=table_name,
                operation=DatabaseOperation(operation),
                old_data=None,  # 不再需要完整行数据
                new_data=None,  # 不再需要完整行数据
                changes=[change.__dict__ for change in changes],  # 转换为字典
                timestamp=timestamp,
                user_id=extracted_user_id,    # 从changes中提取
                tenant_id=extracted_tenant_id,  # 从changes中提取
                ip_address='system',  # 从数据库层面无法获取IP
                user_agent='Database Trigger'
            )

            # 发布事件到内部事件总线
            event_bus_manager = get_event_bus_manager()
            internal_bus = event_bus_manager.get_internal_bus()

            if internal_bus:
                await internal_bus.publish(event)
                logger.debug(f"[BinlogSubscriber] Published event for {operation} on {table_name}, record_id: {record_id}, changes: {len(changes)}")
            else:
                logger.warning(f"[BinlogSubscriber] Internal event bus not available, falling back to direct logging")
                # 如果事件总线不可用，回退到原来的直接记录方式
                await self._fallback_to_direct_logging(table_config, operation, None, None, changes, extracted_tenant_id, extracted_user_id)

        except Exception as e:
            logger.error(f"[BinlogSubscriber] Failed to handle notification: {e}")
    
    def _parse_changes(self, table_config: Dict, operation: str, 
                      old_data: Optional[Dict], new_data: Optional[Dict]) -> List[Dict]:
        """解析数据变更"""
        changes = []
        fields = table_config.get('fields', {})
        
        if operation == 'INSERT':
            # 新增操作
            for field, field_name in fields.items():
                if new_data and field in new_data:
                    value = new_data[field]
                    if value is not None:
                        changes.append({
                            'field': field,
                            'field_name': field_name,
                            'old_value': None,
                            'new_value': str(value),
                            'change_type': 'ADD'
                        })
        
        elif operation == 'UPDATE':
            # 更新操作
            for field, field_name in fields.items():
                old_value = old_data.get(field) if old_data else None
                new_value = new_data.get(field) if new_data else None
                
                # 检查值是否发生变化
                if old_value != new_value:
                    changes.append({
                        'field': field,
                        'field_name': field_name,
                        'old_value': str(old_value) if old_value is not None else None,
                        'new_value': str(new_value) if new_value is not None else None,
                        'change_type': 'MODIFY'
                    })
        
        elif operation == 'DELETE':
            # 删除操作
            for field, field_name in fields.items():
                if old_data and field in old_data:
                    value = old_data[field]
                    if value is not None:
                        changes.append({
                            'field': field,
                            'field_name': field_name,
                            'old_value': str(value),
                            'new_value': None,
                            'change_type': 'REMOVE'
                        })
        
        return changes
    
    def _extract_operator_id(self, data: Optional[Dict]) -> Optional[str]:
        """提取操作者ID"""
        if not data:
            return None
        
        # 尝试从不同字段提取操作者信息
        for field in ['updated_by', 'created_by', 'user_id']:
            if field in data and data[field]:
                return str(data[field])
        
        return None
    
    def _extract_operator_name(self, _data: Optional[Dict]) -> Optional[str]:
        """提取操作者名称"""
        # 这里可以根据operator_id查询用户名，暂时返回None
        return None

    def _extract_tenant_id(self, data: Optional[Dict]) -> Optional[str]:
        """提取租户ID"""
        if not data:
            return None

        # 尝试从不同字段提取租户信息
        for field in ['tenant_id']:
            if field in data and data[field]:
                return str(data[field])

        return None

    async def _fallback_to_direct_logging(self, table_config: Dict, operation: str,
                                        old_data: Optional[Dict], new_data: Optional[Dict],
                                        changes: List, extracted_tenant_id, extracted_user_id) -> None:
        """回退到直接记录日志的方式"""
        try:
            # 构建操作日志（保持原有格式）
            log_data = {
                'operator_id': extracted_user_id,
                'operator_name': extracted_user_id,
                'module': table_config['module'],
                'operation_type': self._map_operation_type(operation),
                'table_name': table_config.get('table_name', ''),
                'record_id': str((new_data or old_data).get('id', '')),
                'ip': 'system',
                'user_agent': 'Database Trigger',
                'tenant_id': extracted_tenant_id,  # 添加 tenant_id 提取
                'changes': [change.__dict__ if hasattr(change, '__dict__') else change for change in changes]
            }

            # 异步记录到ES
            await log_operation(log_data)
            logger.debug(f"[BinlogSubscriber] Fallback logged {operation}")

        except Exception as e:
            logger.error(f"[BinlogSubscriber] Failed to fallback log: {e}")

    def _map_operation_type(self, operation: str) -> str:
        """映射操作类型"""
        mapping = {
            'INSERT': 'CREATE',
            'UPDATE': 'UPDATE',
            'DELETE': 'DELETE'
        }
        return mapping.get(operation, operation)


# 全局binlog订阅服务实例
_binlog_subscriber: Optional[BinlogSubscriber] = None


async def init_binlog_service():
    """初始化binlog订阅服务"""
    # 支持两种环境变量名（向后兼容历史拼写错误）
    binlog_enabled = (
        os.getenv('BINLOG_ENABLED') == 'true' or
        os.getenv('BINGLOG_ENABLED') == 'true'
    )

    if not binlog_enabled:
        logger.info("[BinlogService] Disabled, skipping initialization")
        logger.info("[BinlogService] 提示：要启用 binlog 服务，请设置环境变量 BINLOG_ENABLED=true 或 BINGLOG_ENABLED=true")
        return

    global _binlog_subscriber
    if _binlog_subscriber is None:
        _binlog_subscriber = BinlogSubscriber()
        try:
            await _binlog_subscriber.start()
            logger.info("[BinlogService] Initialized")
        except Exception as e:
            logger.error(f"[BinlogService] Failed to initialize: {e}")
            _binlog_subscriber = None
            # 不抛出异常，允许应用继续运行


async def close_binlog_service():
    """关闭binlog订阅服务"""
    global _binlog_subscriber
    if _binlog_subscriber:
        await _binlog_subscriber.stop()
        _binlog_subscriber = None


def get_binlog_subscriber() -> Optional[BinlogSubscriber]:
    """获取binlog订阅服务实例"""
    return _binlog_subscriber
