"""
涂布运行参数表（拆分自 CoatingSampleData 579-592 行对应字段）
包含时间戳、设备ID，以及涂布模头间隙、泵速、温湿度等运行参数
"""
from sqlalchemy import Column, Integer, Float, String, DateTime
from sqlalchemy.orm import validates

from ..base import BaseModel


class CoatingRunningParams(BaseModel):
    """
    涂布运行参数
    """
    __tablename__ = "coating_running_params"

    timestamp = Column(DateTime, nullable=False, index=True, comment="时间戳")

    # 涂布模头间隙相关
    slot_die_os_gap = Column(Float, nullable=True, comment="涂布模头左侧间隙")
    slot_die_mid_gap = Column(Float, nullable=True, comment="涂布模头中间间隙")
    slot_die_ds_gap = Column(Float, nullable=True, comment="涂布模头右侧间隙")

    # 机器运行参数
    machine_running_speed = Column(Float, nullable=True, comment="机器运行速度")

    # 泵速度相关
    buffer_pump_speed = Column(Float, nullable=True, comment="缓冲泵速度")
    degassing1_pump_speed = Column(Float, nullable=True, comment="脱气泵1速度")
    degassing2_pump_speed = Column(Float, nullable=True, comment="脱气泵2速度")

    # 温度相关
    buffer_adhesion_temperature = Column(Float, nullable=True, comment="缓冲胶水温度")
    degassing1_adhesion_temperature = Column(Float, nullable=True, comment="脱气1胶水温度")
    degassing2_adhesion_temperature = Column(Float, nullable=True, comment="脱气2胶水温度")
    temperature = Column(Float, nullable=True, comment="环境温度")

    # 环境参数
    humidity = Column(Float, nullable=True, comment="环境湿度")

    # 设备标识
    machine_id = Column(String(50), nullable=True, index=True, comment="机器ID")

    def to_dict(self):
        custom_fields = {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'slot_die_os_gap': float(self.slot_die_os_gap) if self.slot_die_os_gap is not None else None,
            'slot_die_mid_gap': float(self.slot_die_mid_gap) if self.slot_die_mid_gap is not None else None,
            'slot_die_ds_gap': float(self.slot_die_ds_gap) if self.slot_die_ds_gap is not None else None,
            'machine_running_speed': float(self.machine_running_speed) if self.machine_running_speed is not None else None,
            'buffer_pump_speed': float(self.buffer_pump_speed) if self.buffer_pump_speed is not None else None,
            'degassing1_pump_speed': float(self.degassing1_pump_speed) if self.degassing1_pump_speed is not None else None,
            'degassing2_pump_speed': float(self.degassing2_pump_speed) if self.degassing2_pump_speed is not None else None,
            'buffer_adhesion_temperature': float(self.buffer_adhesion_temperature) if self.buffer_adhesion_temperature is not None else None,
            'degassing1_adhesion_temperature': float(self.degassing1_adhesion_temperature) if self.degassing1_adhesion_temperature is not None else None,
            'degassing2_adhesion_temperature': float(self.degassing2_adhesion_temperature) if self.degassing2_adhesion_temperature is not None else None,
            'temperature': float(self.temperature) if self.temperature is not None else None,
            'humidity': float(self.humidity) if self.humidity is not None else None,
            'machine_id': self.machine_id,
        }
        return super().to_dict(custom_fields)

    def __repr__(self):
        return (f"<CoatingRunningParams(id={self.id}, timestamp={self.timestamp}, "
                f"machine_id={self.machine_id})>")

    @validates('humidity')
    def validate_humidity(self, key, value):
        if value is not None and (value < 0 or value > 100):
            raise ValueError("湿度值必须在0-100之间")
        return value

    @validates('machine_running_speed')
    def validate_speed(self, key, value):
        if value is not None and value < 0:
            raise ValueError("机器运行速度不能为负数")
        return value

