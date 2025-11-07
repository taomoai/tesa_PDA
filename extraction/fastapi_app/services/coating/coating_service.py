"""
涂料数据服务
处理涂料传感器数据的转换、验证和存储
"""
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from loguru import logger

from ...core.database import get_async_db_context
from ...models.coating import CoatingRunningParams, CoatingDataboxValues
from sqlalchemy import select, desc


class CoatingDataService:
    """涂料数据服务类（分表存储）"""

    @staticmethod
    def _parse_timestamp(timestamp_str: Any) -> Optional[datetime]:
        """
        解析时间戳字符串为datetime对象
        
        Args:
            timestamp_str: 时间戳字符串或datetime对象
            
        Returns:
            datetime: 解析后的时间戳，失败时返回None
        """
        if isinstance(timestamp_str, datetime):
            return timestamp_str
        
        if not timestamp_str:
            return datetime.now()
        
        try:
            # 尝试多种时间格式
            timestamp_formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y/%m/%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
            ]
            
            for fmt in timestamp_formats:
                try:
                    return datetime.strptime(str(timestamp_str), fmt)
                except ValueError:
                    continue
            
            # 尝试使用ISO格式解析
            try:
                from dateutil.parser import parse
                return parse(str(timestamp_str))
            except Exception:
                pass
            
            logger.warning(f"[CoatingDataService] Unable to parse timestamp: {timestamp_str}, using current time")
            return datetime.now()
            
        except Exception as e:
            logger.error(f"[CoatingDataService] Error parsing timestamp {timestamp_str}: {e}")
            return datetime.now()
    
    @staticmethod
    async def save_running_params(event_data: Dict[str, Any]) -> Optional[CoatingRunningParams]:
        try:
            timestamp = CoatingDataService._parse_timestamp(event_data.get('timestamp'))
            if not timestamp:
                logger.error(f"[CoatingDataService] Invalid timestamp: {event_data.get('timestamp')}")
                return None

            data = CoatingDataService._map_running_params_fields(event_data, timestamp)

            async with get_async_db_context() as session:
                db_record = CoatingRunningParams(**data)
                session.add(db_record)
                await session.flush()
                await session.refresh(db_record)
                logger.info(f"[CoatingDataService] Saved running params with ID: {db_record.id}")
                return db_record
        except Exception as e:
            logger.error(f"[CoatingDataService] Error saving running params: {e}")
            logger.error(f"[CoatingDataService] Event data: {event_data}")
            return None

    @staticmethod
    async def save_databox_and_process(event_data: Dict[str, Any]) -> Optional[CoatingDataboxValues]:
        try:
            timestamp = CoatingDataService._parse_timestamp(event_data.get('timestamp'))
            if not timestamp:
                logger.error(f"[CoatingDataService] Invalid timestamp: {event_data.get('timestamp')}")
                return None

            data = CoatingDataService._map_databox_and_process_fields(event_data, timestamp)

            async with get_async_db_context() as session:
                db_record = CoatingDataboxValues(**data)
                session.add(db_record)
                await session.flush()
                await session.refresh(db_record)
                logger.info(f"[CoatingDataService] Saved databox/process with ID: {db_record.id}")
                return db_record
        except Exception as e:
            logger.error(f"[CoatingDataService] Error saving databox/process: {e}")
            logger.error(f"[CoatingDataService] Event data: {event_data}")
            return None

    # ===================== 新增：查询与合并/克隆工具 =====================

    @staticmethod
    async def get_latest_running_params() -> Optional[CoatingRunningParams]:
        try:
            async with get_async_db_context() as session:
                result = await session.execute(
                    select(CoatingRunningParams).order_by(desc(CoatingRunningParams.timestamp)).limit(1)
                )
                return result.scalars().first()
        except Exception as e:
            logger.error(f"[CoatingDataService] Error fetching latest running params: {e}")
            return None

    @staticmethod
    async def get_latest_databox_values() -> Optional[CoatingDataboxValues]:
        try:
            async with get_async_db_context() as session:
                result = await session.execute(
                    select(CoatingDataboxValues).order_by(desc(CoatingDataboxValues.timestamp)).limit(1)
                )
                return result.scalars().first()
        except Exception as e:
            logger.error(f"[CoatingDataService] Error fetching latest databox values: {e}")
            return None

    @staticmethod
    def parse_value_kv_list(value: Any) -> Dict[str, Any]:
        """
        将 value 列表形式 [{"key": val}, ...] 或字典，统一解析为 {key: val}
        """
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            merged: Dict[str, Any] = {}
            for item in value:
                if isinstance(item, dict):
                    for k, v in item.items():
                        merged[str(k)] = v
            return merged
        return {}

    @staticmethod
    def _map_external_to_running_fields(external_map: Dict[str, Any]) -> Dict[str, Any]:
        mapping = {
            'CR.C808.SLOT_DIE_OS_GAP': 'slot_die_os_gap',
            'CR.C808.SLOT_DIE_MID_GAP': 'slot_die_mid_gap',
            'CR.C808.SLOT_DIE_DS_GAP': 'slot_die_ds_gap',
            'CR.C808.RUNNING_STATUS.MACHINE_RUNNING_SPEED': 'machine_running_speed',
            'CR.C808.BUFFER_PUMP_SPEED': 'buffer_pump_speed',
            'CR.C808.DEGASSING1_PUMP_SPEED': 'degassing1_pump_speed',
            'CR.C808.DEGASSING2_PUMP_SPEED': 'degassing2_pump_speed',
            'CR.C808.BUFFER_ADHESION_TEMPERATURE': 'buffer_adhesion_temperature',
            'CR.C808.DEGASSING1_ADHESION_TEMPERATURE': 'degassing1_adhesion_temperature',
            'CR.C808.DEGASSING2_ADHESION_TEMPERATURE': 'degassing2_adhesion_temperature',
            'CR.C808.COATING_HEAD.TEMPERATURE': 'temperature',
            'CR.C808.COATING_HEAD.HUMIDITY': 'humidity',
        }

        data: Dict[str, Any] = {}
        for ext, internal in mapping.items():
            if ext in external_map:
                data[internal] = external_map[ext]
        return data

    @staticmethod
    def _map_external_to_databox_fields(external_map: Dict[str, Any]) -> Dict[str, Any]:
        import re

        data: Dict[str, Any] = {}

        # General/process parameters
        general_mapping = {
            'QMS.Readings.TABReadingsGeneral.0.MdMeterCount': 'md_meter_count',
            'QMS.Readings.TABReadingsGeneral.0.MdSpeed': 'md_speed',
            'QMS.Current.KeyName': 'key_name',
            'QMS.Current.TabRecipeDiffer.0.RdPreset': 'rd_preset',
            'QMS.Current.TabRecipeDiffer.0.RdTolerM': 'rd_toler_m',
            'QMS.Current.TabRecipeDiffer.0.RdTolerP': 'rd_toler_p',
        }

        for ext, internal in general_mapping.items():
            if ext in external_map:
                data[internal] = external_map[ext]

        # DataboxN
        pattern = re.compile(r'^QMS\.Readings\.TABProfileValues\.54\.Databox(\d+)$')
        for key, value in external_map.items():
            m = pattern.match(str(key))
            if m:
                idx = int(m.group(1))
                if 0 <= idx <= 511:
                    data[f'databox{idx:03d}'] = value

        return data

    @staticmethod
    def _merge_with_latest(current: Dict[str, Any], latest_obj: Any, fields: Tuple[str, ...]) -> Dict[str, Any]:
        """
        对缺失字段从最新记录中补全
        """
        if not latest_obj:
            return current
        for f in fields:
            if current.get(f) is None:
                current[f] = getattr(latest_obj, f, None)
        return current

    @staticmethod
    def _running_field_names() -> Tuple[str, ...]:
        return (
            'slot_die_os_gap', 'slot_die_mid_gap', 'slot_die_ds_gap',
            'machine_running_speed', 'buffer_pump_speed',
            'degassing1_pump_speed', 'degassing2_pump_speed',
            'buffer_adhesion_temperature', 'degassing1_adhesion_temperature', 'degassing2_adhesion_temperature',
            'temperature', 'humidity', 'machine_id'
        )

    @staticmethod
    def _databox_field_names() -> Tuple[str, ...]:
        fields = ['machine_id', 'md_meter_count', 'md_speed', 'key_name', 'rd_preset', 'rd_toler_m', 'rd_toler_p']
        fields.extend([f'databox{idx:03d}' for idx in range(512)])
        return tuple(fields)

    @staticmethod
    async def save_running_with_merge(timestamp: Any, external_map: Dict[str, Any]) -> Optional[CoatingRunningParams]:
        ts = CoatingDataService._parse_timestamp(timestamp)
        mapped = CoatingDataService._map_external_to_running_fields(external_map)
        latest = await CoatingDataService.get_latest_running_params()
        merged = CoatingDataService._merge_with_latest(mapped, latest, CoatingDataService._running_field_names())
        merged['timestamp'] = ts
        return await CoatingDataService.save_running_params(merged)

    @staticmethod
    async def save_databox_with_merge(timestamp: Any, external_map: Dict[str, Any]) -> Optional[CoatingDataboxValues]:
        ts = CoatingDataService._parse_timestamp(timestamp)
        mapped = CoatingDataService._map_external_to_databox_fields(external_map)
        latest = await CoatingDataService.get_latest_databox_values()
        merged = CoatingDataService._merge_with_latest(mapped, latest, CoatingDataService._databox_field_names())
        merged['timestamp'] = ts
        return await CoatingDataService.save_databox_and_process(merged)

    @staticmethod
    async def clone_latest_running_with_timestamp(timestamp: Any) -> Optional[CoatingRunningParams]:
        ts = CoatingDataService._parse_timestamp(timestamp)
        latest = await CoatingDataService.get_latest_running_params()
        if not latest:
            # 没有历史记录则写入空模板
            return await CoatingDataService.save_running_params({'timestamp': ts})

        data: Dict[str, Any] = {'timestamp': ts}
        for f in CoatingDataService._running_field_names():
            if f != 'machine_id':
                data[f] = getattr(latest, f, None)
        data['machine_id'] = getattr(latest, 'machine_id', 'default_machine')
        return await CoatingDataService.save_running_params(data)

    @staticmethod
    async def clone_latest_databox_with_timestamp(timestamp: Any) -> Optional[CoatingDataboxValues]:
        ts = CoatingDataService._parse_timestamp(timestamp)
        latest = await CoatingDataService.get_latest_databox_values()
        if not latest:
            return await CoatingDataService.save_databox_and_process({'timestamp': ts})

        data: Dict[str, Any] = {'timestamp': ts}
        for f in CoatingDataService._databox_field_names():
            data[f] = getattr(latest, f, None)
        return await CoatingDataService.save_databox_and_process(data)

    @staticmethod
    def _map_running_params_fields(event_data: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            'timestamp': timestamp,
            'slot_die_os_gap': None,
            'slot_die_mid_gap': None,
            'slot_die_ds_gap': None,
            'machine_running_speed': None,
            'buffer_pump_speed': None,
            'degassing1_pump_speed': None,
            'degassing2_pump_speed': None,
            'buffer_adhesion_temperature': None,
            'degassing1_adhesion_temperature': None,
            'degassing2_adhesion_temperature': None,
            'temperature': None,
            'humidity': None,
            'machine_id': None,
        }

        field_types = {
            'slot_die_os_gap': 'float',
            'slot_die_mid_gap': 'float',
            'slot_die_ds_gap': 'float',
            'machine_running_speed': 'float',
            'buffer_pump_speed': 'float',
            'degassing1_pump_speed': 'float',
            'degassing2_pump_speed': 'float',
            'buffer_adhesion_temperature': 'float',
            'degassing1_adhesion_temperature': 'float',
            'degassing2_adhesion_temperature': 'float',
            'temperature': 'float',
            'humidity': 'float',
            'machine_id': 'str',
        }

        for name, t in field_types.items():
            if name in event_data:
                if t == 'int':
                    data[name] = CoatingDataService._safe_int_convert(event_data[name])
                elif t == 'float':
                    data[name] = CoatingDataService._safe_float_convert(event_data[name])
                else:
                    data[name] = str(event_data[name]) if event_data[name] is not None else None

        if not data['machine_id']:
            data['machine_id'] = 'default_machine'

        return data

    @staticmethod
    def _map_databox_and_process_fields(event_data: Dict[str, Any], timestamp: datetime) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            'timestamp': timestamp,
            'machine_id': None,
            'md_meter_count': None,
            'md_speed': None,
            'key_name': None,
            'rd_preset': None,
            'rd_toler_m': None,
            'rd_toler_p': None,
        }

        # 初始化512个databox字段
        for i in range(512):
            data[f'databox{i:03d}'] = None

        # 直接字段
        simple_fields = {
            'machine_id': 'str',
            'md_meter_count': 'float',
            'md_speed': 'float',
            'key_name': 'str',
            'rd_preset': 'float',
            'rd_toler_m': 'float',
            'rd_toler_p': 'float',
        }

        for name, t in simple_fields.items():
            if name in event_data:
                if t == 'int':
                    data[name] = CoatingDataService._safe_int_convert(event_data[name])
                elif t == 'float':
                    data[name] = CoatingDataService._safe_float_convert(event_data[name])
                else:
                    data[name] = str(event_data[name]) if event_data[name] is not None else None

        # databox 数组
        if 'databox' in event_data and isinstance(event_data['databox'], list):
            for i, value in enumerate(event_data['databox'][:512]):
                data[f'databox{i:03d}'] = CoatingDataService._safe_float_convert(value)

        # databox000..511 直接字段
        for i in range(512):
            field = f'databox{i:03d}'
            if field in event_data:
                data[field] = CoatingDataService._safe_float_convert(event_data[field])

        # value 数组仅当没有明确的 databox 字段时，视为 databox 序列
        if ('databox' not in event_data) and ('value' in event_data) and isinstance(event_data['value'], list):
            for i, value in enumerate(event_data['value'][:512]):
                data[f'databox{i:03d}'] = CoatingDataService._safe_float_convert(value)

        if not data['machine_id']:
            data['machine_id'] = 'default_machine'

        return data
    
    @staticmethod
    def _safe_int_convert(value: Any) -> Optional[int]:
        """
        安全地将值转换为整数
        
        Args:
            value: 要转换的值
            
        Returns:
            int: 转换后的整数，失败时返回None
        """
        if value is None:
            return None
        
        try:
            return int(float(value))  # 先转float再转int，处理"123.0"这种情况
        except (ValueError, TypeError):
            logger.warning(f"[CoatingDataService] Cannot convert to int: {value}")
            return None
    
    @staticmethod
    def _safe_float_convert(value: Any) -> Optional[float]:
        """
        安全地将值转换为浮点数
        
        Args:
            value: 要转换的值
            
        Returns:
            float: 转换后的浮点数，失败时返回None
        """
        if value is None:
            return None
        
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"[CoatingDataService] Cannot convert to float: {value}")
            return None
    
    # 旧的基于单表的查询接口如需保留，请在新表上实现对应查询逻辑