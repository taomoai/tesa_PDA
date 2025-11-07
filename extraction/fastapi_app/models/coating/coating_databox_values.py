"""
测厚仪 Databox 数值表（拆分自 CoatingSampleData 的 512 个 databox 字段）
包含时间戳、设备ID，以及 databox000 ~ databox511 共 512 个厚度数据点
"""
from sqlalchemy import Column, Float, String, DateTime, Integer

from ..base import BaseModel


class CoatingDataboxValues(BaseModel):
    """
    Databox 厚度数据
    """
    __tablename__ = "coating_databox_values"

    # 基本标识
    timestamp = Column(DateTime, nullable=False, index=True, comment="时间戳")
    machine_id = Column(String(50), nullable=True, index=True, comment="机器ID")

    # 合并自 CoatingProcessParams 的工艺与计量参数
    md_meter_count = Column(Float, nullable=True, comment="计米器计数")
    md_speed = Column(Float, nullable=True, comment="MD速度")
    key_name = Column(String(100), nullable=True, comment="产品型号")
    rd_preset = Column(Float, nullable=True, comment="预设值")
    rd_toler_m = Column(Float, nullable=True, comment="公差负值")
    rd_toler_p = Column(Float, nullable=True, comment="公差正值")

    def to_dict(self):
        custom_fields = {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'machine_id': self.machine_id,
            'md_meter_count': float(self.md_meter_count) if self.md_meter_count is not None else None,
            'md_speed': float(self.md_speed) if self.md_speed is not None else None,
            'key_name': self.key_name,
            'rd_preset': float(self.rd_preset) if self.rd_preset is not None else None,
            'rd_toler_m': float(self.rd_toler_m) if self.rd_toler_m is not None else None,
            'rd_toler_p': float(self.rd_toler_p) if self.rd_toler_p is not None else None,
        }
        for i in range(512):
            field_name = f"databox{i:03d}"
            field_value = getattr(self, field_name, None)
            custom_fields[field_name] = float(field_value) if field_value is not None else None
        return super().to_dict(custom_fields)

    def get_databox_values(self) -> list:
        values = []
        for i in range(512):
            values.append(getattr(self, f"databox{i:03d}", None))
        return values

    def set_databox_values(self, values: list):
        for i, value in enumerate(values[:512]):
            setattr(self, f"databox{i:03d}", value)


# 动态定义 512 个 databox 字段
for _i in range(512):
    setattr(
        CoatingDataboxValues,
        f"databox{_i:03d}",
        Column(Float, nullable=True, comment=f"测厚仪数据点{_i:03d}"),
    )

