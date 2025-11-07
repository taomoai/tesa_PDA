"""
主数据业务服务
负责主数据的统一更新业务逻辑
"""
import logging
import re
from typing import Dict, List, Tuple, Type, Any, Optional
import uuid
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import Numeric, update, select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from fastapi_app.core.context import current_tasks_store
from fastapi_app.core.database import get_async_session, get_async_db_context
from fastapi_app.core.event_bus import get_internal_event_bus
from fastapi_app.bus.event import Event
from fastapi_app.bus.topics import Topics
from fastapi_app.utils.tiny_func import simple_exception
from datetime import timezone
from fastapi_app.modules.master_data_service.employee.model import Employee
from fastapi_app.modules.master_data_service.product.model import Product, ProductExtractionConfig
from fastapi_app.modules.master_data_service.supplier.model import Supplier
from fastapi_app.modules.master_data_service.inspection_item.model import InspectionItem, TesaInspectionResult
from fastapi_app.modules.master_data_service.inspection_standard.model import InspectionStandard
from fastapi_app.modules.master_data_service.organization.model import Organization
from fastapi_app.modules.master_data_service.organization.service import OrganizationService
from fastapi_app.modules.master_data_service.product.model import ProductInspectionItemsResult

from fastapi_app.modules.auth_service.user.model import User
from fastapi_app.modules.auth_service.account.model import Account, AccountRole, Role
from fastapi_app.modules.monitor_service.default_monitor.service import InspectionAlgorithmRelationService
from flask_app.modules.common_service.enums.enums import User as UserEnum, Role as RoleEnum
from flask_app.utils.snowflake import snowflake

logger = logging.getLogger(__name__)


class MasterDataService:
    """主数据业务服务类"""
    
    MODEL_MAP = {
        "supplier": Supplier,
        "product": Product,
        "inspection_item_supplier": InspectionItem,
        "inspection_item_customer": InspectionItem,
        "inspection_standard_supplier": InspectionStandard,
        "inspection_standard_customer": InspectionStandard,
        "employee": Employee,
        "organization": Organization,
        'tesa_inspection_result': TesaInspectionResult,
        'supplier_inspection_result': ProductInspectionItemsResult
    }
    
    # 数据类型到用户类型的映射
    USER_TYPE_MAP = {
        "inspection_item_supplier": "supplier",
        "inspection_item_customer": "customer",
        "inspection_standard_supplier": "supplier",
        "inspection_standard_customer": "customer",
    }
    
    # 系统/租户字段，不允许覆盖更新（避免被置为 None）
    EXCLUDED_OVERWRITE_FIELDS = {
        "created_at", "updated_at", "created_by", "updated_by", "tenant_id", "is_delete", "id"
    }

    def _safe_convert_field_value(self, value: Any, column_type: Any) -> Any:
        """
        安全地转换字段值为适当的类型

        Args:
            value: 原始值
            column_type: SQLAlchemy 列类型或 Python 类型

        Returns:
            转换后的值
        """
        if value is None or value == '':
            return None

        # 检查是否是 Numeric/Decimal 类型
        from sqlalchemy import Numeric
        if isinstance(column_type, Numeric) or column_type is Decimal:
            try:
                return Decimal(str(value))
            except (ValueError, TypeError, Exception):
                return None

        # 其他类型保持原样
        return value
    
    def get_supported_data_types(self) -> List[str]:
        """获取支持的主数据类型列表"""
        return list(self.MODEL_MAP.keys())
    
    def validate_data_type(self, data_type: str) -> bool:
        """验证主数据类型是否支持"""
        return data_type in self.MODEL_MAP
    
    def _overwrite_instance_fields(self, instance: Any, payload: Dict, model_cls: Type, data_type: str = None) -> None:
        """
        覆盖实例字段值
        
        Args:
            instance: 数据库实例
            payload: 更新数据
            model_cls: 模型类
            data_type: 数据类型，用于确定 user_type
        """
        table = model_cls.__table__
        primary_keys = {col.key for col in table.primary_key.columns}
        column_names = [col.key for col in table.columns]
        
        for col in column_names:
            # 跳过主键和系统字段
            if col in primary_keys or col in self.EXCLUDED_OVERWRITE_FIELDS:
                continue
            
            # 特殊处理 user_type 字段
            if col == "user_type" and data_type in self.USER_TYPE_MAP:
                setattr(instance, col, self.USER_TYPE_MAP[data_type])
                continue
                
            if col in payload:
                # 获取列类型并进行安全转换
                column = table.columns.get(col)
                if column is not None:
                    converted_value = self._safe_convert_field_value(payload[col], column.type)
                    setattr(instance, col, converted_value)
                else:
                    setattr(instance, col, payload[col])
            else:
                # 覆盖语义：未提供的字段设为 None（系统字段除外）
                # 但不覆盖 user_type 字段，因为它应该由 data_type 决定
                if col != "user_type":
                    setattr(instance, col, None)
    
    def _create_new_instance(self, record_id: str, payload: Dict, model_cls: Type, data_type: str = None) -> Any:
        """
        创建新实例

        Args:
            record_id: 记录ID
            payload: 数据
            model_cls: 模型类
            data_type: 数据类型，用于确定 user_type

        Returns:
            新创建的实例
        """
        # 构造完整对象：未提供的字段设为 None（系统字段除外）
        table = model_cls.__table__
        column_names = [col.key for col in table.columns]

        instance = model_cls(id=record_id)

        # 设置字段值
        for col in column_names:
            if col == "id" or col in self.EXCLUDED_OVERWRITE_FIELDS:
                continue

            # 特殊处理 org_id 字段：所有新增数据的 org_id 都设置为 "-1"
            if col == "org_id":
                setattr(instance, col, "-1")
                continue

            if col in payload:
                # 获取列类型并进行安全转换
                column = table.columns.get(col)
                if column is not None:
                    converted_value = self._safe_convert_field_value(payload[col], column.type)
                    setattr(instance, col, converted_value)
                else:
                    setattr(instance, col, payload[col])
            else:
                # 不自动设置 user_type 为 None，应该由 data_type 决定
                if col != "user_type":
                    setattr(instance, col, None)

        return instance

    def _trigger_supplier_organization_creation(self, supplier_ids: List[str], tenant_id: int) -> None:
        """
        为供应商创建组织并刷新缓存

        Args:
            supplier_ids: 供应商ID列表
            tenant_id: 租户ID
        """
        from fastapi_app.modules.master_data_service.organization.service import OrganizationService
        from fastapi_app.modules.master_data_service.organization.schema import SupplierOrganizationCreate

        async def create_organizations_and_refresh():
            """异步创建组织并刷新缓存"""
            async with get_async_session() as async_db:
                org_service = OrganizationService(async_db)

                # 为每个供应商创建组织
                for supplier_id in supplier_ids:
                    try:
                        # 查询供应商信息
                        supplier = await async_db.get(Supplier, supplier_id)
                        if not supplier:
                            logger.warning(f"供应商 {supplier_id} 不存在，跳过组织创建")
                            continue

                        # 检查组织是否已存在
                        existing_org = await Organization.select_organization_by_code(
                            code=supplier_id,
                            tenant_id=tenant_id,
                            db=async_db
                        )

                        if existing_org:
                            logger.debug(f"供应商 {supplier_id} 的组织已存在，跳过创建")
                            continue

                        # 创建组织
                        supplier_org_data = SupplierOrganizationCreate(
                            supplier_id=supplier_id,
                            name=supplier.name,
                            description=supplier.description
                        )

                        await org_service.trigger_create_supplier_organization(
                            supplier_creation=supplier_org_data,
                            tenant_id=tenant_id,
                            unchange_tag=True
                        )
                        logger.info(f"为供应商 {supplier_id} 创建组织成功")

                    except Exception as e:
                        logger.warning(f"为供应商 {supplier_id} 创建组织失败: {str(e)}")
                        continue

                # 提交事务
                await async_db.commit()

                # 由于是在同一个后台任务内，所以更新后立即刷新缓存
                try:
                    await org_service.trigger_cache_refresh(tenant_id=tenant_id)
                    logger.info(f"租户 {tenant_id} 的组织树缓存刷新成功")
                except Exception as e:
                    logger.warning(f"刷新组织树缓存失败: {str(e)}")

        # 向本次请求上下文的任务暂存器添加后台任务
        task_store = current_tasks_store.get()
        task_store.add_task(create_organizations_and_refresh())

    def _bulk_update_suppliers_by_partner_number(
        self,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> Tuple[int, int, List[str]]:
        """按 code 覆盖更新供应商，支持 coding 映射和默认值校验。"""
        created = 0
        updated = 0
        errors: List[str] = []
        created_supplier_ids: List[str] = []  # 记录新创建的供应商ID

        for idx, record in enumerate(records):
            try:
                # 入参映射：coding -> code
                if 'coding' in record and 'code' not in record:
                    record['code'] = record.get('coding')

                # 校验必要字段
                record_id = record.get("id")
                if not record_id:
                    errors.append(f"record[{idx}] 缺少必需字段 id")
                    continue

                code = record.get('code')
                if not code:
                    errors.append(f"record[{idx}] 缺少必需字段 code/coding")
                    continue

                partner_number = record.get('partner_number')
                if not partner_number:
                    errors.append(f"record[{idx}] 缺少必需字段 partner_number")
                    continue

                # 默认值设定
                record.setdefault('type', 'SUPPLIER')
                record.setdefault('status', 'APPROVED')
                record.setdefault('is_active', True)
                record.setdefault('created_by', 'Mendix')
                record.setdefault('org_id', '-1')

                # 简单邮箱校验（模型里也会再次校验）
                email = record.get('email')
                if email and '@' not in email:
                    errors.append(f"record[{idx}] email 格式不正确")
                    continue

                # 依据 code（及租户）查询是否存在
                query = db.query(Supplier).filter(Supplier.partner_number == partner_number)
                if tenant_id is not None and hasattr(Supplier, 'tenant_id'):
                    query = query.filter(Supplier.tenant_id == tenant_id)
                existing: Optional[Supplier] = query.first()

                if existing:
                    # 覆盖更新（未提供的字段设为 None，排除系统字段）
                    self._overwrite_instance_fields(existing, record, Supplier, 'supplier')
                    # 审计字段
                    if hasattr(existing, 'update_audit_fields'):
                        existing.update_audit_fields()
                    # 确保租户ID不被清空；仅在缺失时补齐
                    if tenant_id is not None and getattr(existing, 'tenant_id', None) is None:
                        setattr(existing, 'tenant_id', tenant_id)
                    updated += 1

                    # 更新后也尝试创建组织（如果不存在）
                    created_supplier_ids.append(existing.id)
                    logger.debug(f"更新记录: supplier[code={code}] -> id={existing.id}")
                else:
                    # 如果 code 不存在，则新建（使用传入 id），并尽量补齐 tenant_id
                    instance = self._create_new_instance(record_id, record, Supplier, 'supplier')
                    if tenant_id is not None and getattr(instance, 'tenant_id', None) is None:
                        setattr(instance, 'tenant_id', tenant_id)
                    if hasattr(instance, 'set_create_audit_fields'):
                        instance.set_create_audit_fields()
                    db.add(instance)
                    created += 1
                    created_supplier_ids.append(record_id)

                    logger.debug(f"创建记录: supplier[code={code}] -> id={record_id}")
            except Exception as e:
                error_msg = f"record[{idx}] 处理失败: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)
                continue

        db.commit()

        # 为所有创建/更新的供应商创建组织并刷新缓存
        if created_supplier_ids and tenant_id is not None:
            self._trigger_supplier_organization_creation(
                supplier_ids=created_supplier_ids,
                tenant_id=tenant_id
            )

        return created, updated, errors

    def _bulk_update_products_by_part_number(
        self,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> Tuple[int, int, List[str]]:
        """按 part_number 覆盖更新产品，支持默认值校验与租户补齐。

        1. 优先按 (part_number, tenant_id) 查询。
        2. 如果找到，则更新该记录。
        3. 如果未找到，再按 (id) 查询。
        4. 如果按 id 找到，则更新该记录（允许 part_number 变更）。
        5. 如果都未找到，则使用 payload 中的 id 创建新记录。
        """
        created = 0
        updated = 0
        errors: List[str] = []

        # 用于检查本批次内的 part_number 唯一性
        part_numbers_in_batch = set()

        for idx, record in enumerate(records):
            try:
                record_id = record.get("id")
                if not record_id:
                    errors.append(f"record[{idx}] 缺少必需字段 id")
                    continue

                part_number = record.get('part_number')

                # 如果 part_number 为空，尝试用 bnr-pv 构建
                if not part_number or part_number == 'null':
                    bnr = record.get('bnr')
                    pv = record.get('pv')

                    if bnr:
                        # 用 bnr-pv 或 bnr 构建 part_number
                        part_number = f"{bnr}-{pv}" if pv else bnr
                        record['part_number'] = part_number
                        logger.debug(f"record[{idx}] 自动生成 part_number: {part_number}")
                    else:
                        errors.append(f"record[{idx}] 缺少必需字段 part_number，且无法从 bnr/pv 构建")
                        continue

                # 检查本批次内的唯一性
                if part_number in part_numbers_in_batch:
                    errors.append(f"record[{idx}] part_number={part_number} 在本批次中重复")
                    continue
                part_numbers_in_batch.add(part_number)

                # 默认值
                record.setdefault('type', 'product')
                record.setdefault('is_active', True)
                record.setdefault('created_by', 'Mendix')
                record.setdefault('units', '件')
                record.setdefault('org_id', '-1')

                # 1. 依据 part_number（及租户）查询是否存在
                query = db.query(Product).filter(Product.part_number == part_number)
                if tenant_id is not None and hasattr(Product, 'tenant_id'):
                    query = query.filter(Product.tenant_id == tenant_id)

                existing_by_part_number: Product | None = query.first()

                if existing_by_part_number:
                    # 2. 按 part_number 找到，执行更新
                    self._overwrite_instance_fields(existing_by_part_number, record, Product, 'product')
                    if hasattr(existing_by_part_number, 'update_audit_fields'):
                        existing_by_part_number.update_audit_fields()
                    if tenant_id is not None and getattr(existing_by_part_number, 'tenant_id', None) is None:
                        setattr(existing_by_part_number, 'tenant_id', tenant_id)
                    updated += 1
                    logger.debug(
                        f"更新记录 (part_number 匹配): product[part_number={part_number}] -> id={existing_by_part_number.id}")
                else:
                    # 3. 按 part_number 未找到，尝试按 id 查询
                    existing_by_id: Product | None = db.get(Product, record_id)

                    if existing_by_id:
                        # 4. 按 id 找到，执行更新（允许 part_number 变更）
                        # 确保租户匹配（如果提供了租户ID）
                        if tenant_id is not None and hasattr(existing_by_id, 'tenant_id'):
                            if getattr(existing_by_id, 'tenant_id', None) != tenant_id:
                                errors.append(f"record[{idx}] ID {record_id} 存在但租户不匹配，跳过")
                                continue

                        self._overwrite_instance_fields(existing_by_id, record, Product, 'product')
                        if hasattr(existing_by_id, 'update_audit_fields'):
                            existing_by_id.update_audit_fields()
                        # 租户ID不应被覆盖，但在缺失时补齐
                        if tenant_id is not None and getattr(existing_by_id, 'tenant_id', None) is None:
                            setattr(existing_by_id, 'tenant_id', tenant_id)
                        updated += 1
                        logger.debug(
                            f"更新记录 (ID 匹配, part_number 变更): product[id={record_id}] -> new part_number={part_number}")
                    else:
                        # 5. 按 id 也未找到，创建新记录
                        instance = self._create_new_instance(record_id, record, Product, 'product')
                        if tenant_id is not None and getattr(instance, 'tenant_id', None) is None:
                            setattr(instance, 'tenant_id', tenant_id)
                        if hasattr(instance, 'set_create_audit_fields'):
                            instance.set_create_audit_fields()
                        db.add(instance)
                        created += 1
                        logger.debug(f"创建记录: product[part_number={part_number}] -> id={record_id}")

            except Exception as e:
                error_msg = f"record[{idx}] 处理失败: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)
                continue

        db.commit()
        return created, updated, errors

    def _parse_date(self, value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            try:
                return datetime.fromisoformat(value).date()
            except Exception:
                return None

    def _preprocess_employee_records(
        self,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> List[Dict]:
        """预处理员工记录：
        - organization_code -> organization_id (如果找不到对应的organization，organization_id为空)
        - 解析 join_date/end_date/birthday
        - 默认 is_active True
        - user_type 默认 inside
        """
        processed: List[Dict] = []
        for record in records:
            rec = dict(record)
            # 组织映射
            org_code = rec.get('organization_code')
            if org_code:
                q = db.query(Organization).filter(Organization.code == org_code)
                if tenant_id is not None and hasattr(Organization, 'tenant_id'):
                    q = q.filter(Organization.tenant_id == tenant_id)
                org = q.first()
                if org:
                    rec['organization_id'] = org.id
                else:
                    # 如果找不到对应的organization，将organization_id设为None
                    rec['organization_id'] = None
            else:
                # 如果没有提供organization_code，将organization_id设为None
                rec['organization_id'] = None

            # 日期解析
            for key in ('join_date', 'end_date', 'birthday'):
                if key in rec and isinstance(rec[key], str):
                    parsed = self._parse_date(rec[key])
                    rec[key] = parsed

            # 默认值
            # 兼容 status -> is_active
            if 'status' in rec and 'is_active' not in rec:
                rec['is_active'] = bool(rec.get('status'))
            rec.setdefault('is_active', True)
            rec['user_type'] = rec.pop('employee_type', None)  # 接收的字段名与数据库字段名映射 employee_type -> user_type
            # 兼容 Location -> location
            if 'Location' in rec and 'location' not in rec:
                rec['location'] = rec.get('Location')

            processed.append(rec)
        return processed

    def _bulk_upsert_employees(
        self,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> Tuple[int, int, List[str]]:
        """按 id 覆盖更新员工，并在创建时创建用户与账号。"""
        created = 0
        updated = 0
        errors: List[str] = []

        # 预处理
        records = self._preprocess_employee_records(records=records, db=db, tenant_id=tenant_id)

        for idx, record in enumerate(records):
            employee_instance = None  # 用于存储当前处理的员工实例
            record_id = None  # 初始化 record_id
            try:
                if not record.get('number') or not record.get('name'):
                    errors.append(f"record[{idx}] 缺少必需字段 number 或 name")
                    continue

                # 使用雪花算法生成唯一的 ID，确保 ID 的统一性
                record_id = snowflake.generate_id()

                existing: Optional[Employee] = db.query(Employee).filter(Employee.number == record.get('number')).first()
                if existing:
                    self._overwrite_instance_fields(existing, record, Employee, 'employee')
                    if hasattr(existing, 'update_audit_fields'):
                        existing.update_audit_fields()
                    if tenant_id is not None and getattr(existing, 'tenant_id', None) is None:
                        setattr(existing, 'tenant_id', tenant_id)
                    employee_instance = existing  # 保存实例引用
                    updated += 1
                else:
                    record.setdefault('created_by', 'Mendix')
                    instance: Employee = self._create_new_instance(str(record_id), record, Employee, 'employee')
                    if tenant_id is not None and getattr(instance, 'tenant_id', None) is None:
                        setattr(instance, 'tenant_id', tenant_id)
                    if hasattr(instance, 'set_create_audit_fields'):
                        instance.set_create_audit_fields()
                    db.add(instance)
                    employee_instance = instance  # 保存实例引用
                    created += 1
            except Exception as e:
                errors.append(f"record[{idx}] 处理失败: {str(e)}")
                logger.warning(errors[-1])
                continue

            # 创建用户与账号
            try:
                raw_email = record.get("email")
                username_value = record.get("number") or str(record_id)
                email = raw_email or f"{username_value}@auto.local"
                existing_user = db.query(User).filter(User.email == email).first()
                if existing_user is None:
                    user = User(
                        username=username_value,
                        email=email,
                        status=UserEnum.Status.ENABLED.value.value,
                        org_id="-1",
                        created_by='Mendix',
                    )
                    try:
                        user.set_password(username_value)
                    except Exception:
                        pass
                    db.add(user)
                    db.flush()
                else:
                    user = existing_user

                if tenant_id is None:
                    errors.append(f"record[{idx}] 缺少 tenant_id，未创建账号")
                else:
                    this_account: Account | None = db.query(Account).filter(
                        Account.user_id == user.id,
                        Account.tenant_id == tenant_id
                    ).first()
                    if this_account is None:
                        this_account = Account(user_id=user.id, tenant_id=tenant_id, org_id="-1", created_by='Mendix')
                        db.add(this_account)
                        db.flush()

                        # 为新创建的账号分配默认角色
                        try:
                            default_role = db.query(Role).filter(
                                Role.code == RoleEnum.Type.NORMAL_ADMIN.value.value,
                                Role.tenant_id == tenant_id,
                                Role.is_delete == False
                            ).first()

                            if default_role:
                                # 检查是否已存在角色关联
                                existing_role = db.query(AccountRole).filter(
                                    AccountRole.account_id == this_account.id,
                                    AccountRole.role_id == default_role.id,
                                    AccountRole.tenant_id == tenant_id
                                ).first()

                                if not existing_role:
                                    account_role = AccountRole(
                                        account_id=this_account.id,
                                        role_id=default_role.id,
                                        tenant_id=tenant_id,
                                        org_id="-1",
                                        created_by='Mendix',
                                    )
                                    db.add(account_role)
                                    logger.debug(f"为账号 {this_account.id} 分配默认角色 NORMAL_ADMIN")
                            else:
                                logger.warning(f"租户 {tenant_id} 未找到默认角色 NORMAL_ADMIN")
                        except Exception as role_e:
                            logger.warning(f"为账号 {this_account.id} 分配角色失败: {str(role_e)}")
                            # 不影响主流程，继续执行

                    # 将 account_id 回写到员工记录中
                    if employee_instance is not None:
                        employee_instance.account_id = this_account.id
                        logger.debug(f"员工 {employee_instance.id} 关联账号 {this_account.id}")
            except Exception as sub_e:
                errors.append(f"record[{idx}] 创建用户/账号失败: {str(sub_e)}")
                continue

        db.commit()
        return created, updated, errors

    def _bulk_update_inspection_standards(
        self,
        data_type: str,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> Tuple[int, int, List[str]]:
        """
        处理检验标准：
        - 根据 bnr+pv 查找/创建 Product（part_number=bnr[-pv]，units 默认“件”，type 默认“成品”）
        - 根据 partner_code 查找 Supplier（按 code）；未找到则记错并跳过
        - inspection_items 中每个项按 name+method 查找/创建 InspectionItem；生成 code
        - 为每个 item 创建/更新一条 InspectionStandard（按 product_id+partner_id+item_id 唯一）
        """
        created = 0
        updated = 0
        errors: List[str] = []
        monitor_creation_data: list[tuple[str, str]] = []  # 用于创建监控器的参数list，[(product_id, inspection_item_id),]

        # 用于跟踪本批次中已处理的检验标准组合，避免重复创建
        # key: (product_id, partner_id, item_id), value: record_index
        processed_standards: Dict[Tuple[str, str, str], int] = {}

        # 用于跟踪本批次中已处理的检测项，避免重复创建
        # key: (name, method, user_type), value: inspection_item_id
        processed_inspection_items: Dict[Tuple[str, str, str], str] = {}

        # 用于跟踪本批次中已处理的产品，避免重复创建
        # key: (part_number, tenant_id), value: product_id
        processed_products: Dict[Tuple[str, Optional[int]], str] = {}

        # 判定 user_type（供应商/客户）
        user_type = self.USER_TYPE_MAP.get(data_type, 'supplier')

        for idx, record in enumerate(records):
            try:
                bnr: Optional[str] = record.get('bnr')
                pv: Optional[str] = record.get('pv')
                partner_code: Optional[str] = record.get('partner_code')
                items: List[Dict] = record.get('inspection_items') or []

                # 对关键字段进行首尾空格处理
                bnr = (bnr or '').strip()
                pv = (pv or '').strip() if pv else None
                partner_code = (partner_code or '').strip()

                if not bnr:
                    errors.append(f"record[{idx}] 缺少必需字段 bnr")
                    continue
                if not partner_code:
                    errors.append(f"record[{idx}] 缺少必需字段 partner_code")
                    continue
                if not items:
                    errors.append(f"record[{idx}] inspection_items 为空")
                    continue

                # 1) 获取 Supplier（按 code=partner_code）
                sup_q = db.query(Supplier).filter(Supplier.partner_number == partner_code)
                if tenant_id is not None and hasattr(Supplier, 'tenant_id'):
                    sup_q = sup_q.filter(Supplier.tenant_id == tenant_id)
                supplier: Optional[Supplier] = sup_q.first()
                if not supplier:
                    if partner_code == 'tesa':
                        supplier = Supplier(
                            id=str(uuid.uuid4()),
                            partner_number=partner_code,
                            code=partner_code,
                            name='TESA',
                            tenant_id=tenant_id,
                            is_active=True,
                            org_id="-1",
                            created_by='Mendix',
                        )
                        if hasattr(supplier, 'set_create_audit_fields'):
                            supplier.set_create_audit_fields()
                        db.add(supplier)
                        db.flush()
                        logger.debug(f"创建供应商: partner_number={partner_code}")
                    else:
                        errors.append(f"record[{idx}] 未找到供应商(code={partner_code})，已跳过该记录")
                        continue

                # 2) 获取/创建 Product（按 bnr+pv）
                # 构建 part_number: 如果有 pv 则用 bnr-pv，否则只用 bnr
                part_number = f"{bnr}-{pv}" if pv else bnr

                # 检查本批次中是否已经处理过相同的产品
                product_key = (part_number, tenant_id)
                if product_key in processed_products:
                    # 使用已处理的产品ID
                    product_id = processed_products[product_key]
                    # 从数据库获取产品实例
                    product = db.get(Product, product_id)
                    logger.debug(f"复用已处理的产品: part_number={part_number}, id={product_id}")
                else:
                    # 查询是否已存在该 part_number 的产品
                    prod_q = db.query(Product).filter(Product.part_number == part_number)
                    if tenant_id is not None and hasattr(Product, 'tenant_id'):
                        prod_q = prod_q.filter(Product.tenant_id == tenant_id)
                    product: Optional[Product] = prod_q.first()

                    if not product:
                        # 创建 Product，补齐必要字段
                        # 注意：这里保证了 part_number 的唯一性，因为我们先查询再创建
                        product = Product(
                            id=str(uuid.uuid4()),
                            type='product',
                            part_number=part_number,
                            units='件',
                            description=None,
                            category=None,
                            tenant_id=tenant_id,
                            is_active=True,
                            supplier_id=supplier.id,
                            org_id="-1",
                            created_by='Mendix',
                        )
                        # 设置扩展字段（bnr/pv）
                        if hasattr(product, 'bnr'):
                            setattr(product, 'bnr', bnr)
                        if hasattr(product, 'pv'):
                            setattr(product, 'pv', pv)
                        if hasattr(product, 'set_create_audit_fields'):
                            product.set_create_audit_fields()
                        db.add(product)
                        db.flush()
                        logger.debug(f"创建产品: part_number={part_number}, bnr={bnr}, pv={pv}")
                    else:
                        # 检查现有产品是否缺少 supplier_id，如果缺少则补充
                        if not product.supplier_id:
                            product.supplier_id = supplier.id
                            if hasattr(product, 'update_audit_fields'):
                                product.update_audit_fields()
                            logger.debug(f"补充产品供应商ID: part_number={part_number}, supplier_id={supplier.id}")

                    # 记录已处理的产品
                    processed_products[product_key] = product.id

                # 3) 逐个 inspection_item 处理
                for j, item in enumerate(items):
                    name = item.get('item_name') or item.get('name')
                    method = item.get('item_method') or item.get('method')
                    units = item.get('unit')
                    item_type = item.get('Inspection_Type') or item.get('inspection_type')
                    target = item.get('Target') or item.get('target')

                    # 对关键字段进行首尾空格处理
                    name = (name or '').strip()
                    method = (method or '').strip()
                    units = (units or '').strip() if units else None
                    item_type = (item_type or '').strip() if item_type else None

                    lsl = self._safe_convert_field_value(item.get('Lower_Limit') or item.get('lower_Limit'), Numeric(10, 4))
                    usl = self._safe_convert_field_value(item.get('Upper_Limit') or item.get('upper_Limit'), Numeric(10, 4))
                    lcl = self._safe_convert_field_value(item.get('lcl'), Numeric(10, 4))
                    ucl = self._safe_convert_field_value(item.get('ucl'), Numeric(10, 4))
                    alias = item.get('alias')
                    is_include = item.get('is_include') or True

                    # 对 alias 也进行空格处理
                    alias = (alias or '').strip() if alias else None

                    if not name or not method:
                        errors.append(f"record[{idx}].items[{j}] 缺少必需字段 item_name/item_method")
                        continue

                    # 检查本批次中是否已经处理过相同的检测项
                    inspection_item_key = (name, method, user_type)
                    if inspection_item_key in processed_inspection_items:
                        # 使用已处理的检测项ID
                        inspection_item_id = processed_inspection_items[inspection_item_key]
                        # 从数据库获取检测项实例（用于后续标准创建）
                        inspection_item = db.get(InspectionItem, inspection_item_id)
                        logger.debug(f"复用已处理的检测项: name={name}, method={method}, id={inspection_item_id}")
                    else:
                        # 查找/创建 InspectionItem（按 name+method+user_type）
                        itm_q = db.query(InspectionItem).filter(
                            InspectionItem.name == name,
                            InspectionItem.inspection_method == method,
                            InspectionItem.user_type == user_type,
                        )
                        if tenant_id is not None and hasattr(InspectionItem, 'tenant_id'):
                            itm_q = itm_q.filter(InspectionItem.tenant_id == tenant_id)
                        inspection_item: Optional[InspectionItem] = itm_q.first()
                        if inspection_item:
                            # 更新非关键字段
                            inspection_item.value_units = units or inspection_item.value_units
                            inspection_item.type = item_type or inspection_item.type
                            if alias and hasattr(inspection_item, 'alias'):
                                inspection_item.alias = alias
                                inspection_item.description = alias
                            if hasattr(inspection_item, 'update_audit_fields'):
                                inspection_item.update_audit_fields()
                            # 记录已处理的检测项
                            processed_inspection_items[inspection_item_key] = inspection_item.id
                        else:
                            # 生成稳定 code（基于 name+method）
                            stable_code = f"ITM-{uuid.uuid5(uuid.NAMESPACE_DNS, (tenant_id and str(tenant_id) or '') + name + '|' + method)}"
                            inspection_item = InspectionItem(
                                id=str(uuid.uuid4()),
                                code=stable_code,
                                name=name,
                                type=item_type,
                                user_type=user_type,
                                inspection_method=method,
                                value_units=units,
                                tenant_id=tenant_id,
                                is_active=True,
                                group=item.get('group'),
                                org_id="-1",
                                created_by='Mendix',
                            )
                            if alias and hasattr(inspection_item, 'alias'):
                                inspection_item.alias = alias
                                inspection_item.description = alias
                            if hasattr(inspection_item, 'set_create_audit_fields'):
                                inspection_item.set_create_audit_fields()
                            db.add(inspection_item)
                            try:
                                db.flush()
                                # 记录已处理的检测项
                                processed_inspection_items[inspection_item_key] = inspection_item.id
                            except IntegrityError:
                                # 可能是并发创建导致的唯一约束冲突，重新查询
                                db.rollback()
                                itm_q = db.query(InspectionItem).filter(
                                    InspectionItem.name == name,
                                    InspectionItem.inspection_method == method,
                                    InspectionItem.user_type == user_type,
                                )
                                if tenant_id is not None and hasattr(InspectionItem, 'tenant_id'):
                                    itm_q = itm_q.filter(InspectionItem.tenant_id == tenant_id)
                                inspection_item = itm_q.first()
                                if not inspection_item:
                                    # 如果还是找不到，说明是其他错误，重新抛出
                                    raise
                                else:
                                    # 记录已处理的检测项
                                    processed_inspection_items[inspection_item_key] = inspection_item.id

                    # 将product_id与inspection_item_id添加到根据默认配置创建monitor的参数中， 在最后统一创建
                    monitor_creation_data.append((product.id, inspection_item.id))

                    # 4) 创建/更新 InspectionStandard（按 product+partner+item 唯一）
                    # 首先检查本批次中是否已经处理过相同的组合
                    standard_key = (product.id, supplier.id, inspection_item.id)
                    if standard_key in processed_standards:
                        previous_record_idx = processed_standards[standard_key]
                        errors.append(f"record[{idx}].items[{j}] 与 record[{previous_record_idx}] 中的检验标准重复 (product_id={product.id}, partner_id={supplier.id}, item_id={inspection_item.id})，已跳过")
                        continue

                    std_q = db.query(InspectionStandard).filter(
                        InspectionStandard.product_id == product.id,
                        InspectionStandard.partner_id == supplier.id,
                        InspectionStandard.item_id == inspection_item.id,
                    )
                    if tenant_id is not None and hasattr(InspectionStandard, 'tenant_id'):
                        std_q = std_q.filter(InspectionStandard.tenant_id == tenant_id)
                    std: Optional[InspectionStandard] = std_q.first()

                    if std:
                        std.target = target
                        std.lsl = lsl
                        std.usl = usl
                        std.lcl = lcl
                        std.ucl = ucl
                        std.type = (record.get('type') or 'OQC')
                        std.user_type = user_type
                        std.is_active = True
                        std.is_include = is_include
                        if hasattr(std, 'update_audit_fields'):
                            std.update_audit_fields()
                        updated += 1
                        # 记录已处理的检验标准组合
                        processed_standards[standard_key] = idx
                    else:
                        std = InspectionStandard(
                            id=str(uuid.uuid4()),
                            type=record.get('type') or 'OQC',
                            product_id=product.id,
                            partner_id=supplier.id,
                            item_id=inspection_item.id,
                            user_type=user_type,
                            default_value=None,
                            is_required=None,
                            sort_order=None,
                            target=target,
                            lsl=lsl,
                            lcl=lcl,
                            ucl=ucl,
                            usl=usl,
                            tenant_id=tenant_id,
                            is_active=True,
                            is_include=is_include,
                            org_id="-1",
                        )
                        if hasattr(std, 'set_create_audit_fields'):
                            std.set_create_audit_fields()
                        db.add(std)
                        try:
                            db.flush()
                            created += 1
                            # 记录已处理的检验标准组合
                            processed_standards[standard_key] = idx
                        except IntegrityError:
                            # 可能是并发创建导致的唯一约束冲突，重新查询并更新
                            db.rollback()
                            std_q = db.query(InspectionStandard).filter(
                                InspectionStandard.product_id == product.id,
                                InspectionStandard.partner_id == supplier.id,
                                InspectionStandard.item_id == inspection_item.id,
                            )
                            if tenant_id is not None and hasattr(InspectionStandard, 'tenant_id'):
                                std_q = std_q.filter(InspectionStandard.tenant_id == tenant_id)
                            existing_std = std_q.first()
                            if existing_std:
                                # 更新现有记录
                                existing_std.target = target
                                existing_std.lsl = lsl
                                existing_std.usl = usl
                                existing_std.lcl = lcl
                                existing_std.ucl = ucl
                                existing_std.type = (record.get('type') or 'OQC')
                                existing_std.user_type = user_type
                                existing_std.is_active = True
                                existing_std.is_include = is_include
                                if hasattr(existing_std, 'update_audit_fields'):
                                    existing_std.update_audit_fields()
                                updated += 1
                                # 记录已处理的检验标准组合
                                processed_standards[standard_key] = idx
                            else:
                                # 如果还是找不到，说明是其他错误，重新抛出
                                raise

            except Exception as e:
                errors.append(f"record[{idx}] 处理失败: {str(e)}")
                logger.warning(errors[-1])
                continue

        # 在提交前，为所有涉及的产品构建提取配置
        try:
            self._build_extraction_configs_for_products(db, tenant_id)
        except Exception as e:
            logger.warning(f"自动构建产品提取配置失败: {str(e)}")
            # 不影响主流程，只记录警告

        db.commit()

        # 记录去重统计信息
        total_items_in_records = sum(len(record.get('inspection_items', [])) for record in records)
        unique_items_created = len(processed_inspection_items)
        unique_products_processed = len(processed_products)
        logger.info(f"检测项去重统计: 总数={total_items_in_records}, 去重后={unique_items_created}, 节省={total_items_in_records - unique_items_created}")
        logger.info(f"产品去重统计: 记录数={len(records)}, 唯一产品={unique_products_processed}, 节省={len(records) - unique_products_processed}")

        async def create_monitors_from_default(_monitor_creation_data: list[tuple[str, str]]):
            """根据 product_id、inspection_item_id 创建 Monitor"""
            async with get_async_db_context() as async_db:  # 自动提交
                service = InspectionAlgorithmRelationService(async_db)
                for product_id, inspection_item_id in _monitor_creation_data:
                    try:
                        await service.trigger_monitor_creation_from_default(product_id, inspection_item_id, tenant_id=tenant_id)
                    except Exception as e:
                        logger.error(f"根据Monitor默认配置，对产品的质量检测项创建Monitor监控项失败: {simple_exception(e)}")
                        # 不影响主流程，只记录日志即可

        # 向本次请求上下文的任务暂存器添加后台任务
        task_store = current_tasks_store.get()
        task_store.add_task(create_monitors_from_default(monitor_creation_data))
        return created, updated, errors

    def _bulk_upsert_organizations(
        self,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> Tuple[int, int, List[str]]:
        """按 (tenant_id, code) 覆盖更新组织，支持 parent_code 与 manager(员工工号)。
        创建或更新组织后，会更新所有匹配的员工记录的organization_id。"""
        created = 0
        updated = 0
        errors: List[str] = []
        # 记录所有处理过的组织，用于后续更新员工记录
        processed_organizations: List[Tuple[str, str]] = []  # [(org_id, org_code), ...]

        for idx, record in enumerate(records):
            try:
                code = record.get('code')
                name = record.get('name')
                if not code or not name:
                    errors.append(f"record[{idx}] 缺少必需字段 code 或 name")
                    continue

                # 查询现有 org（按 code + tenant）
                q = db.query(Organization).filter(Organization.code == code)
                if tenant_id is not None and hasattr(Organization, 'tenant_id'):
                    q = q.filter(Organization.tenant_id == tenant_id)
                org: Optional[Organization] = q.first()

                # 解析父级与负责人
                parent_id_value: Optional[str] = None
                if parent_code := record.get('parent_code'):
                    pq = db.query(Organization).filter(Organization.code == parent_code)
                    if tenant_id is not None and hasattr(Organization, 'tenant_id'):
                        pq = pq.filter(Organization.tenant_id == tenant_id)
                    parent = pq.first()
                    if parent:
                        parent_id_value = parent.id

                manager_id_value: Optional[str] = None
                if manager_no := record.get('manager'):
                    eq = db.query(Employee).filter(Employee.number == manager_no)
                    if tenant_id is not None and hasattr(Employee, 'tenant_id'):
                        eq = eq.filter(Employee.tenant_id == tenant_id)
                    manager_emp = eq.first()
                    if manager_emp:
                        manager_id_value = manager_emp.id

                # 状态映射
                is_active_value = record.get('status')
                if is_active_value is None:
                    is_active_value = True

                if org:
                    # 覆盖字段（不通过通用覆盖，避免将未提供字段置 None；仅更新给定字段与映射字段）
                    org.name = name
                    if 'description' in record:
                        org.description = record.get('description')
                    if parent_id_value is not None:
                        org.parent_id = parent_id_value
                    if manager_id_value is not None and hasattr(org, 'manager_id'):
                        setattr(org, 'manager_id', manager_id_value)
                    org.is_active = bool(is_active_value)
                    if hasattr(org, 'update_audit_fields'):
                        org.update_audit_fields()
                    org.type = 'tesa'
                    updated += 1
                    # 记录更新的组织
                    processed_organizations.append((org.id, code))
                else:
                    org = Organization(
                        id=str(uuid.uuid4()),
                        code=code,
                        name=name,
                        description=record.get('description'),
                        type='tesa',    
                        parent_id=parent_id_value,
                        tenant_id=tenant_id,
                        is_active=bool(is_active_value),
                        org_id="-1",
                        created_by='Mendix',
                    )
                    if manager_id_value is not None and hasattr(org, 'manager_id'):
                        setattr(org, 'manager_id', manager_id_value)
                    if hasattr(org, 'set_create_audit_fields'):
                        org.set_create_audit_fields()
                    db.add(org)
                    created += 1
                    # 记录新创建的组织
                    processed_organizations.append((org.id, code))
            except Exception as e:
                errors.append(f"record[{idx}] 处理失败: {str(e)}")
                logger.warning(errors[-1])
                continue

        # 先提交组织的创建/更新
        db.commit()

        # 更新员工记录的organization_id
        self._update_employees_organization_id(processed_organizations, db, tenant_id)

        # 刷新缓存
        if tenant_id is not None:
            OrganizationService.add_task_trigger_cache_refresh(tenant_id)

        return created, updated, errors

    def _update_employees_organization_id(
        self,
        processed_organizations: List[Tuple[str, str]],
        db: Session,
        tenant_id: Optional[int],
    ) -> None:
        """
        根据组织的code更新员工记录的organization_id

        Args:
            processed_organizations: 处理过的组织列表 [(org_id, org_code), ...]
            db: 数据库会话
            tenant_id: 租户ID
        """
        for org_id, org_code in processed_organizations:
            try:
                # 使用 select 和 update 语句：为了便于迁移为异步方法
                # 查询所有organization_code匹配的员工记录
                employee_query = select(Employee).where(Employee.organization_code == org_code)
                if tenant_id is not None and hasattr(Employee, 'tenant_id'):
                    employee_query = employee_query.where(Employee.tenant_id == tenant_id)
                employees = db.execute(employee_query).scalars().all()

                if not employees:
                    continue

                # 批量更新这些员工的organization_id
                employee_ids = [e.id for e in employees]
                employee_update_stmt = update(Employee).where(Employee.id.in_(employee_ids)).values(
                    organization_id=org_id,
                    updated_by='Mendix',
                ).execution_options(synchronize_session=False)
                updated_count: int = db.execute(employee_update_stmt).rowcount

                # 根据这些员工对应的account_id，再同步更新accounts.belong_org
                account_ids = [e.account_id for e in employees if e.account_id]
                if account_ids:
                    account_update_stmt = update(Account).where(Account.id.in_(account_ids)).values(
                        belong_org=org_id,
                    ).execution_options(synchronize_session=False)
                    db.execute(account_update_stmt)

                if updated_count > 0:
                    logger.info(f"更新了 {updated_count} 个员工记录的organization_id，组织code: {org_code}, 组织id: {org_id}")

            except Exception as e:
                logger.warning(f"更新员工organization_id失败，组织code: {org_code}, 错误: {str(e)}")
                continue

        # 提交员工记录的更新
        db.commit()

    def bulk_update_master_data(
        self, 
        data_type: str, 
        records: List[Dict], 
        db: Session,
        tenant_id: Optional[int] = None,
    ) -> Tuple[int, int, List[str]]:
        """
        批量更新主数据
        
        Args:
            data_type: 主数据类型
            records: 记录列表
            db: 数据库会话
            tenant_id: 租户ID
            
        Returns:
            Tuple[created_count, updated_count, errors]
            
        Raises:
            ValueError: 数据类型不支持或记录为空
            SQLAlchemyError: 数据库操作错误
        """
        if not self.validate_data_type(data_type):
            raise ValueError(f"Unsupported data_type: {data_type}")
        
        if not records:
            return 0, 0, []
        
        model_cls = self.MODEL_MAP[data_type]
        created = 0
        updated = 0
        errors: List[str] = []
        
        logger.info(f"开始批量更新主数据: {data_type}, 记录数: {len(records)}")
        
        try:
            # 特殊处理：supplier 按 code 进行覆盖更新，同时支持字段映射与默认值
            if model_cls is Supplier:
                created, updated, errors = self._bulk_update_suppliers_by_partner_number(
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors
            # 特殊处理：employee 专用分支
            if model_cls is Employee:
                created, updated, errors = self._bulk_upsert_employees(
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors
            # 特殊处理：inspection_standard（供应商/客户）分支
            if model_cls is InspectionStandard:
                created, updated, errors = self._bulk_update_inspection_standards(
                    data_type=data_type,
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors
            # 特殊处理：product 按 part_number 进行覆盖更新
            if model_cls is Product:
                created, updated, errors = self._bulk_update_products_by_part_number(
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors
            # 特殊处理：organization 按 code 进行覆盖更新
            if model_cls is Organization:
                created, updated, errors = self._bulk_upsert_organizations(
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors

            if model_cls is TesaInspectionResult:
                created, updated, errors = self._bulk_upsert_tesa_inspection_results(
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors

            if model_cls is ProductInspectionItemsResult:
                created, updated, errors, created_records_info = self._bulk_upsert_product_inspection_items_results(
                    records=records,
                    db=db,
                    tenant_id=tenant_id,
                )
                logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
                return created, updated, errors
            
            # 提交事务
            db.commit()
            logger.info(f"主数据更新完成: {data_type}, 创建: {created}, 更新: {updated}, 错误: {len(errors)}")
            
        except SQLAlchemyError as e:
            db.rollback()
            error_msg = f"数据库操作失败: {str(e)}"
            logger.error(error_msg)
            raise SQLAlchemyError(error_msg) from e
        except Exception as e:
            db.rollback()
            error_msg = f"更新操作失败: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg) from e
        
        return created, updated, errors

    def _bulk_upsert_tesa_inspection_results(
        self,
        records: List[Dict],
        db: Session,
        tenant_id: Optional[int],
    ) -> Tuple[int, int, List[str]]:
        """
        批量存储 TESA 检测结果数据

        处理逻辑：
        1. 遍历每条记录的 inspection_items 数组
        2. 根据 item_name + item_method 查询检测项，不存在则创建
        3. 将每个 inspection_items 元素打平存储为独立的 TesaInspectionResult 记录
        """
        created = 0
        updated = 0
        errors: List[str] = []

        for idx, record in enumerate(records):
            try:
                # 验证必需字段
                bnr = record.get('bnr')
                pv = record.get('pv')
                supplier_code = record.get('supplier_code', "")
                batch_no = record.get('batch_no', "")
                jumbo_batch_no = record.get('jumbo_batch_no')
                date_str = record.get('date')
                inspection_items = record.get('inspection_items', [])

                if not bnr:
                    errors.append(f"record[{idx}] 缺少必需字段 bnr")
                    continue
                if not pv:
                    errors.append(f"record[{idx}] 缺少必需字段 pv")
                    continue
                if not supplier_code:
                    errors.append(f"record[{idx}] 缺少必需字段 supplier_code")
                    continue
                if not date_str:
                    errors.append(f"record[{idx}] 缺少必需字段 date")
                    continue
                if not inspection_items:
                    errors.append(f"record[{idx}] inspection_items 不能为空")
                    continue

                # 解析日期
                try:
                    if isinstance(date_str, str):
                        inspection_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        inspection_date = date_str
                except Exception:
                    errors.append(f"record[{idx}] date 格式不正确: {date_str}")
                    continue

                # 处理每个检测项
                for item_idx, item in enumerate(inspection_items):
                    try:
                        item_name = item.get('item_name')
                        item_method = item.get('item_method')
                        group = item.get('group')
                        result = item.get('result')
                        extra = item.get('extra')

                        if not item_name:
                            errors.append(f"record[{idx}].inspection_items[{item_idx}] 缺少必需字段 item_name")
                            continue
                        if not result:
                            errors.append(f"record[{idx}].inspection_items[{item_idx}] 缺少必需字段 result")
                            continue

                        # 查找或创建检测项
                        inspection_item = self._find_or_create_inspection_item(
                            item_name=item_name,
                            item_method=item_method,
                            group=group,
                            db=db,
                            tenant_id=tenant_id
                        )

                        # 创建 TESA 检测结果记录
                        tesa_result = TesaInspectionResult(
                            id=str(uuid.uuid4()),
                            bnr=bnr,
                            pv=pv,
                            supplier_code=supplier_code,
                            batch_no=batch_no,
                            jumbo_batch_no=jumbo_batch_no,
                            date=inspection_date,
                            inspection_id=inspection_item.id,
                            inspection_name=inspection_item.name,
                            inspection_method=item_method,
                            group=group,
                            result=result,
                            extra=extra,
                            tenant_id=tenant_id,
                            is_active=True,
                            org_id="-1",
                            created_by='Mendix',
                        )

                        if hasattr(tesa_result, 'set_create_audit_fields'):
                            tesa_result.set_create_audit_fields()

                        db.add(tesa_result)
                        created += 1

                    except Exception as e:
                        errors.append(f"record[{idx}].inspection_items[{item_idx}] 处理失败: {str(e)}")
                        continue

            except Exception as e:
                errors.append(f"record[{idx}] 处理失败: {str(e)}")
                logger.warning(errors[-1])
                continue

        db.commit()
        return created, updated, errors

    def _find_or_create_inspection_item(
        self,
        item_name: str,
        item_method: Optional[str],
        user_type: Optional[str],
        group: Optional[str],
        db: Session,
        tenant_id: Optional[int]
    ) -> InspectionItem:
        """
        根据检测项名称和方法查找检测项，如果不存在则创建新的检测项
        """
        # 构建查询条件
        query = db.query(InspectionItem).filter(InspectionItem.name == item_name)

        if tenant_id is not None:
            query = query.filter(InspectionItem.tenant_id == tenant_id)

        # 如果有检测方法，也加入查询条件
        if item_method:
            query = query.filter(InspectionItem.inspection_method == item_method)
        
        if user_type:
            query = query.filter(InspectionItem.user_type == user_type)

        # 查询现有检测项
        existing_item = query.first()

        if existing_item:
            logger.debug(f"找到现有检测项: {existing_item.id} - {existing_item.name}")
            return existing_item

        # 如果不存在，创建新的检测项
        logger.info(f"创建新检测项: {item_name}")
        new_item = InspectionItem(
            id=str(uuid.uuid4()),
            code=str(uuid.uuid4()).replace('-', '').upper()[:20],  # 生成唯一编码
            name=item_name,
            type="TESA检测项",  # 默认类型
            user_type="supplier",  # 默认为供应商类型
            inspection_method=item_method,
            group=group,
            tenant_id=tenant_id,
            is_active=True,
            org_id="-1",
            created_by='Mendix',
        )

        # 设置审计字段
        if hasattr(new_item, 'set_create_audit_fields'):
            new_item.set_create_audit_fields()

        db.add(new_item)
        db.flush()  # 立即刷新以获取ID

        return new_item

    def _build_extraction_configs_for_products(self, db: Session, tenant_id: Optional[int]):
        """为所有有检测标准的产品构建提取配置

        Args:
            db: 数据库会话
            tenant_id: 租户ID
        """
        try:
            # 查询所有有检测标准但没有提取配置的产品
            products_with_standards = db.query(InspectionStandard.product_id).distinct()
            if tenant_id is not None:
                products_with_standards = products_with_standards.filter(InspectionStandard.tenant_id == tenant_id)

            product_ids = [row[0] for row in products_with_standards.all()]

            if not product_ids:
                return

            created_count = 0
            for product_id in product_ids:
                # 获取该产品的所有检测标准中的检测项
                standards_query = db.query(InspectionStandard.item_id).filter(
                    InspectionStandard.product_id == product_id,
                    InspectionStandard.is_delete == False
                )
                if tenant_id is not None:
                    standards_query = standards_query.filter(InspectionStandard.tenant_id == tenant_id)

                inspection_item_ids = [row[0] for row in standards_query.distinct().all()]

                if not inspection_item_ids:
                    continue

                # 为每个检测项创建提取配置（如果不存在）
                for i, item_id in enumerate(inspection_item_ids):
                    # 检查是否已存在配置
                    existing_config = db.query(ProductExtractionConfig).filter(
                        ProductExtractionConfig.product_id == product_id,
                        ProductExtractionConfig.inspection_item_id == item_id,
                        ProductExtractionConfig.is_delete == False
                    ).first()

                    if not existing_config:
                        # 创建新的提取配置
                        config = ProductExtractionConfig(
                            id=str(uuid.uuid4()),
                            product_id=product_id,
                            inspection_item_id=item_id,
                            is_enabled=True,
                            sort_order=i + 1,
                            tenant_id=tenant_id,
                            is_active=True,
                            org_id="-1",
                            created_by='Mendix',
                        )

                        # 设置审计字段
                        if hasattr(config, 'set_create_audit_fields'):
                            config.set_create_audit_fields('system')

                        db.add(config)
                        created_count += 1

            if created_count > 0:
                db.flush()  # 刷新以确保数据写入
                logger.info(f"自动创建了 {created_count} 个产品提取配置")

        except Exception as e:
            logger.error(f"构建产品提取配置时发生错误: {str(e)}")
            raise

    def _bulk_upsert_product_inspection_items_results(self, records: List[Dict], db: Session, tenant_id: Optional[int]) -> Tuple[int, int, List[str], List[Dict]]:
        """
        批量存储产品检验项结果数据

        records: List[Dict] = [
            {
                "bnr": "",
                "pv": "",
                "partner_number": "",
                "batch_no": "",
                "jumbo_no": "",
                "tesa_po_no": "",
                "test_date": "",
                "inspection_items": [
                    {
                        "inspection_name": "",
                        "inspection_method": "",
                        "inspection_value": ""
                    },
                ]
            }
        ]

        Returns:
            Tuple[int, int, List[str], List[Dict]]: (created, updated, errors, created_records_info)
            其中 created_records_info 是创建的记录信息列表，用于后续触发事件
        """
        created = 0
        updated = 0
        errors: List[str] = []
        created_records_info: List[Dict] = []  # 收集创建的记录信息

        for idx, record in enumerate(records):
            try:
                # 验证必需字段
                bnr = record.get('bnr')
                pv = record.get('pv', "")
                partner_number = record.get('partner_number')
                batch_no = record.get('batch_no')
                jumbo_no = record.get('jumbo_no')
                tesa_po_no = record.get('tesa_po_no')
                test_date_str = record.get('test_date')
                inspection_items = record.get('inspection_items', [])

                if not bnr:
                    errors.append(f"record[{idx}] 缺少必需字段 bnr")
                    continue
                if not partner_number:
                    errors.append(f"record[{idx}] 缺少必需字段 partner_number")
                    continue
                if not inspection_items:
                    errors.append(f"record[{idx}] inspection_items 不能为空")
                    continue

                # 解析测试日期
                test_date = None
                if test_date_str:
                    try:
                        if isinstance(test_date_str, str):
                            test_date = datetime.fromisoformat(test_date_str.replace('Z', '+00:00'))
                        else:
                            test_date = test_date_str
                    except Exception:
                        errors.append(f"record[{idx}] test_date 格式不正确: {test_date_str}")
                        continue

                # 根据 bnr 和 pv 获取 product_id
                product = db.query(Product).filter(
                    Product.bnr == bnr,
                    Product.pv == pv,
                    Product.tenant_id == tenant_id
                ).first()

                if not product:
                    errors.append(f"record[{idx}] 根据 bnr={bnr}, pv={pv}, tenant_id={tenant_id} 未找到产品")
                    continue

                product_id = product.id
                nart = product.part_number  # 使用产品的 part_number 作为 nart

                # 根据 partner_number 获取 supplier_id
                supplier = db.query(Supplier).filter(
                    Supplier.partner_number  == partner_number,
                    Supplier.tenant_id == tenant_id
                ).first()

                if not supplier:
                    errors.append(f"record[{idx}] 根据 partner_number={partner_number}, tenant_id={tenant_id} 未找到供应商")
                    continue

                supplier_id = supplier.id

                # 处理每个检测项
                for item_idx, item in enumerate(inspection_items):
                    try:
                        inspection_name = item.get('inspection_name')
                        inspection_method = item.get('inspection_method')
                        inspection_value = item.get('inspection_value')

                        if not inspection_name:
                            errors.append(f"record[{idx}].inspection_items[{item_idx}] 缺少必需字段 inspection_name")
                            continue

                        # 查找或创建检测项
                        inspection_item = self._find_or_create_inspection_item(
                            item_name=inspection_name,
                            item_method=inspection_method,
                            user_type="supplier",
                            group="",
                            db=db,
                            tenant_id=tenant_id
                        )

                        # 生成 task_id（使用雪花算法）
                        task_id = str(snowflake.generate_id())

                        # 创建 ProductInspectionItemsResult 记录
                        result_record = ProductInspectionItemsResult(
                            task_id=task_id,
                            product_id=product_id,
                            supplier_id=supplier_id,
                            org_id="-1",
                            batch_no=batch_no,
                            nart=nart,
                            tesa_po_no=tesa_po_no,
                            jumbo_no=jumbo_no,
                            test_date=test_date,
                            inspection_id=inspection_item.id,
                            inspection_name=inspection_name,
                            inspection_value=inspection_value,
                            inspection_method=inspection_method,
                            inspection_type='normal',  # 默认为 normal
                            tenant_id=tenant_id,
                            is_active=True,
                            created_by='Mendix',
                        )

                        if hasattr(result_record, 'set_create_audit_fields'):
                            result_record.set_create_audit_fields()

                        db.add(result_record)
                        created += 1

                        # 收集创建的记录信息，用于后续触发事件
                        created_records_info.append({
                            "task_id": task_id,
                            "product_id": product_id,
                            "inspection_id": inspection_item.id,
                            "tenant_id": tenant_id,
                            "org_id": "-1"
                        })

                    except Exception as e:
                        errors.append(f"record[{idx}].inspection_items[{item_idx}] 处理失败: {str(e)}")
                        logger.warning(errors[-1])
                        continue

            except Exception as e:
                errors.append(f"record[{idx}] 处理失败: {str(e)}")
                logger.warning(errors[-1])
                continue

        db.commit()

        logger.info(f"[ProductInspectionItemsResult] 批量存储产品检验项结果数据完成，创建: {created}, 更新: {updated}, 错误: {len(errors)}")

        # 数据提交后，触发 Monitor 执行 SPC 计算
        if created > 0:
            async def trigger_monitor_spc_calculation():
                """异步触发 Monitor 执行 SPC 计算"""
                try:
                    logger.info(f"[Monitor SPC] 准备触发 Monitor 执行 SPC 计算，共 {len(created_records_info)} 条记录")

                    # 为每条记录发布事件
                    event_bus = get_internal_event_bus()
                    for record_info in created_records_info:
                        try:
                            # 直接使用已收集的记录信息构建事件 payload
                            event_payload = {
                                "task_id": record_info["task_id"],
                                "product_id": record_info["product_id"],
                                "inspection_id": record_info["inspection_id"],
                                "tenant_id": record_info["tenant_id"],
                                "org_id": record_info["org_id"]
                            }

                            # 创建并发布事件
                            event = Event(
                                topic=Topics.INTERNAL_OQC_DATA,
                                source="master_data_service",
                                payload=event_payload,
                                timestamp=datetime.now(tz=timezone.utc)
                            )

                            await event_bus.publish(event, retry=True, max_retries=2, timeout=10.0)
                            logger.info(f"[Monitor SPC] 事件发布成功: task_id={record_info['task_id']}, inspection_id={record_info['inspection_id']}, tenant_id={record_info['tenant_id']}, org_id={record_info['org_id']}")

                        except Exception as e:
                            logger.error(f"[Monitor SPC] 事件发布失败: task_id={record_info['task_id']}, 错误: {str(e)}")
                            # 单个事件发布失败不应阻止其他事件
                            continue

                    logger.info(f"[Monitor SPC] Monitor SPC 计算触发完成")

                except Exception as e:
                    logger.error(f"[Monitor SPC] 触发 Monitor SPC 计算失败: {str(e)}")
                    # 不影响主流程，只记录日志即可

            # 向本次请求上下文的任务暂存器添加后台任务
            try:
                task_store = current_tasks_store.get()
                task_store.add_task(trigger_monitor_spc_calculation())
            except LookupError:
                # 在测试环境或没有请求上下文的情况下，直接执行异步任务
                logger.warning("[Monitor SPC] 无法获取任务存储器，跳过后台任务注册")

        return created, updated, errors, created_records_info




# 创建全局实例
master_data_service = MasterDataService()