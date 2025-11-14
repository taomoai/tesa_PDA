from pathlib import Path
from typing import List, Optional

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
from pydantic import BaseModel, Field

matplotlib.use("Agg")  # 使用非GUI后端
import base64
from io import BytesIO

import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# 全局变量：数据文件的基础目录
BASE_DIR = Path(__file__).parent.parent

"""
# Agents
关于胶带产品的核心信息。

##  product信息表

### 产品信息表
保存路径： `data/df_product.csv`， 分隔符为`|`
核心列说明：
- `Product Spe`: 产品的唯一ID
- `Product_type`: 产品类型，`single_liner`表示单面胶（一层liner），`double_liner` 表示双面胶（两层liner）
- `Item No.`: 产品属性的id， 格式为PXXXX或PPXXXX， X是数字
- `Item Description`: 关于属性的描述
- `property_key`: 产品的属性，格式为： `pp4079##g/m²##j0pm0005##`, `pp4079` 表示Item No, `g/m²`表示单位，`j0pm0005`表示测试方法。
- `property_value`: 属性的值
- `lb` | `ub`: 表明属性的下 上界。


### 扩展product信息表
扩展产品信息表路径： `data/df_product_extended.csv`, 分隔符为 `|`

核心列名说明：
- `Product_Spec`： 胶带产品id
- `Product_type：` 产品类型：1双面胶，0单面胶
    - double_liner构成方式：in-liner | open-adhensive | backing | cover-adhesive | out-liner
    - single_liner构成方式：liner | open-adhesive | backing | cover-adhesive

- `PXXX_[lb|ub|value|target_value]`: PXXXX表明产品的某一种属性
    - PXXXX_lb / PXXXX_ub 表明属性的下 上界， 
    - PXXXX_value 表明属性的原始值
    - PXXXX_target_value 表明属性的值，一般由lb 和 ub 取均值得到
        - 特殊情况：属性值为单边情况，如 >1000, 那么只有lb有值，ub为NaN。
        - 对于属性值为非数值类型的属性，例如颜色，则PXXXX_value字段存储具体的值，PXXXX_lb和PXXXX_ub均为NaN。

- `Liner_NART`： 表明liner部分使用的liner NART。是否有值取决于product_type
- `In_Liner_NART`: in_liner 部分使用的liner NART
- `Out_Liner_NART`： out_liner 部分使用的liner NART
- `Open_Adhesive_NART`： open side 使用的adhesive NART
- `Cover_Adhesive_NART`: cover side 使用的adhesive NART
- `Backing_NART`： backing部分使用的NART

## 材料表
### adhesive
数据路径： `data/df_adhesive_properties.csv`，分隔符为 `|`
- `Adhesive`: adhesive NART
- `property_key`: 材料的属性名。格式`adhesive##peel adhesion (n/cm)##sus##`, `adhesive` 表示这是adhesive材料，`peel adhesion (n/cm)`表示属性名，`sus`表示测试方法。
- `property_value`: 属性对应的raw value
- `target_value`: 属性对应的解析后的值

### liner
数据路径： `data/df_liner_properties.csv`，分隔符为 `|`
- `Liner` ： liner NART
- `property_key`: 材料的属性名。格式`liner##thickness##µm##`, `liner` 表示这是liner材料，`thickness`表示属性名，`µm`表示属性值的单位。
- `property_value`: 属性对应的raw value
- `target_value`： 属性对应的解析后的值


### backing
数据路径： `data/df_backing_properties.csv`，分隔符为 `|`
- `Backing`: backing NART
- `property_key`: 材料的属性名。格式`backing##tensile strength cd##`, `backing` 表示这是backing材料，`tensile strength cd`表示属性名
- `property_value`: 属性对应的raw value
- `target_value`: 属性对应的解析后的值



## item表
路径： `data/item_no_name_mapping.csv`，分隔符为 `|`
- `Item_No`: item no, 格式PXXXX, X为数字
- `Item_Name`: item no 对应的name。

"""


class Property(BaseModel):
    """
    胶带的某一属性
    """

    item_no: str = Field(default="", description="属性的Item No")
    property_name: str = Field(default="", description="属性的名称")
    property_value: Optional[float] = Field(
        default=None, description="属性的解析值（数值形式）"
    )
    test_method: Optional[str] = Field(default=None, description="属性的测试方法")


class SearchProperty(BaseModel):
    """
    搜索得到的属性
    """

    property: Property = Field(..., description="搜索得到属性")
    expect_value_lb: Optional[float] = Field(default=None, description="搜索的属性下界")
    expect_value_ub: Optional[float] = Field(default=None, description="搜索的属性上界")
    match_score: Optional[float] = Field(default=None, description="属性的匹配得分")


class Product(BaseModel):
    """胶带产品信息"""

    product_spec: str = Field(default="", description="胶带产品id")

    product_type: str = Field(
        default="", description="产品类型，single_liner或double_liner"
    )
    Liner_NART: Optional[str] = Field(default=None, description="单面胶的liner NART")
    In_Liner_NART: Optional[str] = Field(default=None, description="内层liner NART")
    Out_Liner_NART: Optional[str] = Field(default=None, description="外层liner NART")
    Open_Adhesive_NART: Optional[str] = Field(
        default=None, description="开放侧adhesive NART"
    )
    Cover_Adhesive_NART: Optional[str] = Field(
        default=None, description="覆盖侧adhesive NART"
    )
    Backing_NART: Optional[str] = Field(default=None, description="背衬材料NART")

    properties: List[SearchProperty] = Field(default=[], description="产品的属性列表")
    match_score: float = Field(default=0.0, description="产品的匹配得分")


class ApproximateSearch:
    def __init__(self):
        """
        通过加载产品和材料表来初始化ProductSearch类。
        """
        self.df_product = pd.read_csv(BASE_DIR / "data/df_product.csv", sep="|")
        self.df_product_extended = pd.read_csv(
            BASE_DIR / "data/df_product_extended.csv", sep="|"
        )
        self.df_adhesive = pd.read_csv(
            BASE_DIR / "data/df_adhesive_properties.csv", sep="|"
        )
        self.df_liner = pd.read_csv(BASE_DIR / "data/df_liner_properties.csv", sep="|")
        self.df_backing = pd.read_csv(
            BASE_DIR / "data/df_backing_properties.csv", sep="|"
        )
        self.df_item_no = pd.read_csv(
            BASE_DIR / "data/item_no_name_mapping.csv", sep="|"
        )

        # 创建映射字典以快速查找：Item_No -> Item_Name
        self.item_name_mapping = dict(
            zip(self.df_item_no["Item_No"], self.df_item_no["Item_Name"])
        )

    def _filter_by_property_range(
        self,
        df: pd.DataFrame,
        item_nos: List[str],
        lb: Optional[float],
        ub: Optional[float],
        tolerance_ratio: float,
    ) -> pd.DataFrame:
        """
        通用的属性范围过滤函数。

        根据给定的Item No列表和上下界，过滤满足条件的产品。
        支持容差机制，允许属性值在指定范围外一定比例内也被匹配。

        特殊处理：如果产品的所有相关属性都是NaN（即产品没有该属性数据），
        则保留该产品，认为该属性不适用，跳过此项检查。

        参数：
            df: 要过滤的DataFrame
            item_nos: Item No列表，函数会对所有Item No进行OR匹配
            lb: 属性值下界（可选）
            ub: 属性值上界（可选）
            tolerance_ratio: 容差比例

        返回：
            过滤后的DataFrame
        """
        # 如果上下界都为None，直接返回原DataFrame
        if lb is None and ub is None:
            return df

        # 用于标记哪些产品满足条件（值在范围内）
        combined_mask = pd.Series([False] * len(df), index=df.index)

        # 用于标记哪些产品至少有一个相关属性有值
        has_any_value_mask = pd.Series([False] * len(df), index=df.index)

        for item_no in item_nos:
            target_value_col = f"{item_no}_target_value"

            # 如果列不存在则跳过
            if target_value_col not in df.columns:
                print(f"Warning: Column '{target_value_col}' not found in data, skipping...")
                continue

            # 标记该列有非NaN值的产品
            has_value = df[target_value_col].notna()
            has_any_value_mask = has_any_value_mask | has_value

            if lb is not None and ub is not None:
                # 指定了上下界：计算容差范围
                range_width = ub - lb

                # 当lb == ub时（精确匹配），使用更大的容差倍数以匹配接近的产品
                if abs(range_width) < 1e-5:
                    # 使用lb 乘以 tolerance_ratio 作为容差
                    tolerance = (
                        abs(lb) * tolerance_ratio if lb != 0 else 1.0 * tolerance_ratio
                    )
                else:
                    tolerance = range_width * tolerance_ratio

                # 扩展范围：允许target_value在[lb - tolerance, ub + tolerance]内
                extended_lb = lb - tolerance
                extended_ub = ub + tolerance

                mask = (
                    has_value
                    & (df[target_value_col] >= extended_lb)
                    & (df[target_value_col] <= extended_ub)
                )
            elif ub is not None:
                # 仅指定上界：允许超出上界一定比例
                tolerance = ub * tolerance_ratio
                extended_ub = ub + tolerance

                mask = has_value & (df[target_value_col] <= extended_ub)
            else:
                # 仅指定下界：允许低于下界一定比例
                assert lb is not None
                tolerance = lb * tolerance_ratio
                extended_lb = lb - tolerance

                mask = has_value & (df[target_value_col] >= extended_lb)
            combined_mask = combined_mask | mask

        # 最终过滤逻辑：
        # 1. 如果产品至少有一个相关属性有值，则必须满足范围条件（combined_mask为True）
        # 2. 如果产品的所有相关属性都是NaN，则保留该产品（认为该属性不适用）
        final_mask = combined_mask | ~has_any_value_mask

        return df[final_mask]

    def _build_product_list(
        self,
        product_specs: List[str],
        total_thickness_item_nos: List[str],
        open_side_pa_item_nos: List[str],
        cover_side_pa_item_nos: List[str],
        removable_force_item_nos: List[str],
        holding_power_item_nos: List[str],
        cover_coating_weight_item_nos: List[str],
        open_coating_weight_item_nos: List[str],
        total_thickness_lb: Optional[float],
        total_thickness_ub: Optional[float],
        PA_SUS_open_side_lb: Optional[float],
        PA_SUS_open_side_ub: Optional[float],
        PA_SUS_covered_side_lb: Optional[float],
        PA_SUS_covered_side_ub: Optional[float],
        Remove_force_lb: Optional[float],
        Remove_force_ub: Optional[float],
        Holding_Power_lb: Optional[float],
        Holding_Power_ub: Optional[float],
        cover_coating_weight_lb: Optional[float],
        cover_coating_weight_ub: Optional[float],
        open_coating_weight_lb: Optional[float],
        open_coating_weight_ub: Optional[float],
    ) -> List[Product]:
        """
        根据产品规格列表构建完整的产品信息列表。

        参数：
            product_specs: 产品规格列表
            *_item_nos: 各属性对应的Item No列表
            *_lb/*_ub: 各属性的搜索范围

        返回：
            List[Product]: 包含详细属性信息的产品列表
        """
        products = []

        # 定义所有需要查询的属性及其搜索范围
        property_configs = [
            (
                total_thickness_item_nos,
                total_thickness_lb,
                total_thickness_ub,
                "Total thickness",
            ),
            (
                open_side_pa_item_nos,
                PA_SUS_open_side_lb,
                PA_SUS_open_side_ub,
                "Open SUS PA",
            ),
            (
                cover_side_pa_item_nos,
                PA_SUS_covered_side_lb,
                PA_SUS_covered_side_ub,
                "Cover SUS PA",
            ),
            (
                removable_force_item_nos,
                Remove_force_lb,
                Remove_force_ub,
                "Removable Force",
            ),
            (
                holding_power_item_nos,
                Holding_Power_lb,
                Holding_Power_ub,
                "Holding Power",
            ),
            (
                cover_coating_weight_item_nos,
                cover_coating_weight_lb,
                cover_coating_weight_ub,
                "Cover Coating Weight",
            ),
            (
                open_coating_weight_item_nos,
                open_coating_weight_lb,
                open_coating_weight_ub,
                "Open Coating Weight",
            ),
        ]

        for product_spec in product_specs:
            search_properties = []

            # 查询该产品的所有相关属性
            for item_nos, search_lb, search_ub, description in property_configs:
                # 如果搜索条件为空，跳过该属性
                if search_lb is None and search_ub is None:
                    continue

                # 遍历每个可能的item_no
                for item_no in item_nos:
                    # 从df_product中查询该产品的该属性
                    product_records = self.df_product[
                        (self.df_product["Product Spec"] == product_spec)
                        & (self.df_product["Item No."] == item_no)
                    ]

                    # 如果没有找到记录，跳过
                    if product_records.empty:
                        continue

                    # 取第一条记录（通常每个产品的每个Item No只有一条记录）
                    record = product_records.iloc[0]

                    # 解析property_key获取测试方法
                    property_key = record.get("property_key", "")
                    test_method = None
                    if pd.notna(property_key):
                        # property_key格式: pp4079##g/m²##j0pm0005##
                        parts = property_key.split("##")
                        if len(parts) >= 3:
                            test_method = parts[2]

                    # 从df_product中获取property_value (原始字符串值，如 "100 ± 10")
                    property_value_str = record.get("property_value")
                    # 确保property_value是字符串类型
                    if pd.notna(property_value_str):
                        property_value_str = str(property_value_str)
                    else:
                        property_value_str = None

                    # 从df_product_extended中获取target_value (数值)
                    # 查找对应产品的target_value列
                    target_value_col = f"{item_no}_target_value"
                    target_value = None

                    extended_record = self.df_product_extended[
                        self.df_product_extended["Product_Spec"] == product_spec
                    ]

                    if (
                        not extended_record.empty
                        and target_value_col in self.df_product_extended.columns
                    ):
                        target_value_raw = extended_record.iloc[0].get(target_value_col)
                        if pd.notna(target_value_raw):
                            target_value = float(target_value_raw)

                    # 创建Property对象
                    # property_value: 原始字符串值（如 "100 ± 10"）
                    # target_value: 解析后的数值
                    prop = Property(
                        item_no=item_no,
                        property_name=description,
                        property_value=target_value,
                        test_method=test_method,
                    )

                    # 计算匹配得分
                    match_score = self._calculate_match_score(
                        target_value, search_lb, search_ub
                    )

                    # 创建SearchProperty对象
                    search_prop = SearchProperty(
                        property=prop,
                        expect_value_lb=search_lb,
                        expect_value_ub=search_ub,
                        match_score=match_score,
                    )

                    search_properties.append(search_prop)
                    # 找到一个匹配的item_no后就跳出内层循环
                    break

            # 从df_product_extended中获取产品的其他字段
            extended_record = self.df_product_extended[
                self.df_product_extended["Product_Spec"] == product_spec
            ]

            # 初始化产品字段的默认值
            product_type = ""
            liner_nart = None
            in_liner_nart = None
            out_liner_nart = None
            open_adhesive_nart = None
            cover_adhesive_nart = None
            backing_nart = None

            # 如果找到了扩展记录，提取字段
            if not extended_record.empty:
                row = extended_record.iloc[0]

                # 获取产品类型
                product_type_value = row.get("Product_type")
                if pd.notna(product_type_value):
                    # Product_type在df_product_extended中为0或1，需要转换为single_liner或double_liner
                    product_type = (
                        "double_liner" if product_type_value == 1 else "single_liner"
                    )

                # 获取各种NART字段
                liner_nart = (
                    row.get("Liner_NART") if pd.notna(row.get("Liner_NART")) else None
                )
                in_liner_nart = (
                    row.get("In_Liner_NART")
                    if pd.notna(row.get("In_Liner_NART"))
                    else None
                )
                out_liner_nart = (
                    row.get("Out_Liner_NART")
                    if pd.notna(row.get("Out_Liner_NART"))
                    else None
                )
                open_adhesive_nart = (
                    row.get("Open_Adhesive_NART")
                    if pd.notna(row.get("Open_Adhesive_NART"))
                    else None
                )
                cover_adhesive_nart = (
                    row.get("Cover_Adhesive_NART")
                    if pd.notna(row.get("Cover_Adhesive_NART"))
                    else None
                )
                backing_nart = (
                    row.get("Backing_NART")
                    if pd.notna(row.get("Backing_NART"))
                    else None
                )

            # 创建Product对象
            product = Product(
                product_spec=product_spec,
                product_type=product_type,
                Liner_NART=liner_nart,
                In_Liner_NART=in_liner_nart,
                Out_Liner_NART=out_liner_nart,
                Open_Adhesive_NART=open_adhesive_nart,
                Cover_Adhesive_NART=cover_adhesive_nart,
                Backing_NART=backing_nart,
                properties=search_properties,
            )
            products.append(product)

        return products

    def approximate_product_search(
        self,
        total_thickness_lb: Optional[float] = None,
        total_thickness_ub: Optional[float] = None,
        colour: Optional[List[str]] = None,
        PA_SUS_open_side_lb: Optional[float] = None,
        PA_SUS_open_side_ub: Optional[float] = None,
        PA_SUS_covered_side_lb: Optional[float] = None,
        PA_SUS_covered_side_ub: Optional[float] = None,
        Remove_force_lb: Optional[float] = None,
        Remove_force_ub: Optional[float] = None,
        Holding_Power_lb: Optional[float] = None,
        Holding_Power_ub: Optional[float] = None,
        cover_coating_weight_lb: Optional[float] = None,
        cover_coating_weight_ub: Optional[float] = None,
        open_coating_weight_lb: Optional[float] = None,
        open_coating_weight_ub: Optional[float] = None,
        tolerance_ratio: float = 0.8,
    ) -> tuple[List[Product], str]:
        """
        根据给定的筛选条件搜索产品。
        你不要精确匹配各个属性值，而是寻找在指定范围内的产品，或者包含指定特征的产品。

        参数：
            total_thickness_lb (float, optional): 胶带总厚度的下界。
            total_thickness_ub (float, optional): 胶带总厚度的上界。
            colour (List[str], optional): 胶带背衬(backing)的颜色列表，可以指定多个颜色。支持：透明、白色、蓝色、黑色。
            PA_SUS_open_side_lb (float, optional): open面不锈钢剥离力的下界。
            PA_SUS_open_side_ub (float, optional): open面不锈钢剥离力的上界。
            PA_SUS_covered_side_lb (float, optional): cover面不锈钢剥离力的下界。
            PA_SUS_covered_side_ub (float, optional): cover面不锈钢剥离力的上界。
            Remove_force_lb (float, optional): 离型纸剥离力的下界。
            Remove_force_ub (float, optional): 离型纸剥离力的上界。
            Holding_Power_lb (float, optional): 持粘力的下界。
            Holding_Power_ub (float, optional): 持粘力的上界。
            cover_coating_weight_lb (float, optional): cover面涂布重量的下界。
            cover_coating_weight_ub (float, optional): cover面涂布重量的上界。
            open_coating_weight_lb (float, optional): open面涂布重量的下界。
            open_coating_weight_ub (float, optional): open面涂布重量的上界。
            tolerance_ratio (float, optional): 容差比例，默认为0.2（20%）。用于扩展搜索范围，允许属性值在指定范围外一定比例内也被匹配。

        返回：
            List[Product]: 满足条件的产品列表。
            str: 搜索结果的雷达图的Base64编码字符串。
        """
        total_thickness_item_nos = ["P4433"]

        # open side pa 对应的item no
        open_side_pa_item_nos = ["P4005", "P4144"]

        # cover side pa 对应的item no
        cover_side_pa_item_nos = ["P4006", "P4145"]

        # removable force 对应的item no
        removable_force_item_nos = [
            "P4004",
            "P4127",
            "P4140",
            "P4141",
            "P4169",
            "P4170",
        ]

        # holding power 对应的item no
        holding_power_item_nos = [
            "P4041",  # Holding power/steel, open side (10N; RT)##min##
            "P4042",  # Holding power/steel, covered side (10N; RT)##min##
            "P4148",  # Holding power/steel, inside (10N;RT)##min##
            "P4149",  # Holding power/steel, outside (10N;RT)##min##
            "P4211",  # Holding power/steel, open side (10N;40°C)##min##
            "P4212",  # Holding power/steel, covered side (10N;40°C)##min##
            "P4213",  # Holding power/steel, open side (10N;70°C)##min##
            "P4214",  # Holding power/steel, covered side (10N;70°C)##min##
        ]

        # 将前端输入的color映射为backing_colour列的值
        color_to_backing_colour = {
            "透明": "Transparent",
            "白色": "White",
            "蓝色": "Blue",
            "黑色": "Black",
        }

        cover_coating_weight_item_nos = [
            "PP4079",  # Adhesive weight of 1st coating##g/m²## (第一层涂层粘合剂重量)
        ]
        open_coating_weight_item_nos = [
            "PP4080",  # Adhesive weight of 2nd coating##g/m²## (第二层涂层粘合剂重量)
        ]

        # 从扩展dataframe中的所有产品开始
        df = self.df_product_extended.copy()

        # 按总厚度过滤
        df = self._filter_by_property_range(
            df,
            total_thickness_item_nos,
            total_thickness_lb,
            total_thickness_ub,
            tolerance_ratio,
        )

        # 按PA SUS open面过滤
        df = self._filter_by_property_range(
            df,
            open_side_pa_item_nos,
            PA_SUS_open_side_lb,
            PA_SUS_open_side_ub,
            tolerance_ratio,
        )

        # 按PA SUS cover面过滤
        df = self._filter_by_property_range(
            df,
            cover_side_pa_item_nos,
            PA_SUS_covered_side_lb,
            PA_SUS_covered_side_ub,
            tolerance_ratio,
        )

        # 按Remove force过滤
        df = self._filter_by_property_range(
            df,
            removable_force_item_nos,
            Remove_force_lb,
            Remove_force_ub,
            tolerance_ratio,
        )

        # 按Holding Power过滤
        df = self._filter_by_property_range(
            df,
            holding_power_item_nos,
            Holding_Power_lb,
            Holding_Power_ub,
            tolerance_ratio,
        )

        # 按cover coating weight过滤
        df = self._filter_by_property_range(
            df,
            cover_coating_weight_item_nos,
            cover_coating_weight_lb,
            cover_coating_weight_ub,
            tolerance_ratio,
        )

        # 按open coating weight过滤
        df = self._filter_by_property_range(
            df,
            open_coating_weight_item_nos,
            open_coating_weight_lb,
            open_coating_weight_ub,
            tolerance_ratio,
        )

        # 按颜色过滤（backing颜色）- 使用df_product_extended中的backing_colour列
        if colour is not None and len(colour) > 0:
            # 将前端颜色输入映射为backing_colour列的值
            backing_colour_values = [color_to_backing_colour.get(c, c) for c in colour]

            # 检查backing_colour列是否存在
            if "backing_colour" in df.columns:
                # 过滤backing_colour在指定颜色列表中的产品
                df = df[df["backing_colour"].isin(backing_colour_values)]

        # 拼接最终的产品列表
        product_specs = df["Product_Spec"].unique().tolist()
        products = self._build_product_list(
            product_specs=product_specs,
            total_thickness_item_nos=total_thickness_item_nos,
            open_side_pa_item_nos=open_side_pa_item_nos,
            cover_side_pa_item_nos=cover_side_pa_item_nos,
            removable_force_item_nos=removable_force_item_nos,
            holding_power_item_nos=holding_power_item_nos,
            cover_coating_weight_item_nos=cover_coating_weight_item_nos,
            open_coating_weight_item_nos=open_coating_weight_item_nos,
            total_thickness_lb=total_thickness_lb,
            total_thickness_ub=total_thickness_ub,
            PA_SUS_open_side_lb=PA_SUS_open_side_lb,
            PA_SUS_open_side_ub=PA_SUS_open_side_ub,
            PA_SUS_covered_side_lb=PA_SUS_covered_side_lb,
            PA_SUS_covered_side_ub=PA_SUS_covered_side_ub,
            Remove_force_lb=Remove_force_lb,
            Remove_force_ub=Remove_force_ub,
            Holding_Power_lb=Holding_Power_lb,
            Holding_Power_ub=Holding_Power_ub,
            cover_coating_weight_lb=cover_coating_weight_lb,
            cover_coating_weight_ub=cover_coating_weight_ub,
            open_coating_weight_lb=open_coating_weight_lb,
            open_coating_weight_ub=open_coating_weight_ub,
        )

        # 计算每个产品的总体匹配分数
        products = self._calculate_and_assign_match_scores(products)

        radar = self.draw_match_radar(products)

        return products, radar

    def _calculate_and_assign_match_scores(
        self, products: List[Product]
    ) -> List[Product]:
        """
        计算并分配每个产品的总体匹配分数

        参数:
            products: 产品列表

        返回:
            List[Product]: 更新了match_score的产品列表
        """
        for product in products:
            if not product.properties:
                product.match_score = 0.0
                continue

            # 计算所有属性的平均匹配分数
            total_score = 0.0
            for search_prop in product.properties:
                if search_prop.match_score is not None:
                    total_score += search_prop.match_score
                else:
                    # 如果match_score为None，重新计算
                    score = self._calculate_match_score(
                        search_prop.property.property_value,
                        search_prop.expect_value_lb,
                        search_prop.expect_value_ub,
                    )
                    search_prop.match_score = score
                    total_score += score

            # 计算平均分数作为产品的总体匹配分数
            product.match_score = total_score / len(product.properties)

        return products

    def _get_product_dimension_scores(
        self, products: List[Product], property_names: List[str]
    ) -> dict:
        """
        为每个产品获取各属性维度的匹配分数（用于雷达图绘制）

        参数:
            products: 产品列表（已经计算好match_score）
            property_names: 属性名称列表（有序）

        返回:
            dict: 产品规格到分数列表的映射 {product_spec: [score1, score2, ...]}
        """
        product_scores = {}

        for product in products:
            scores = []

            # 为每个属性维度获取已经计算好的匹配分数
            for prop_name in property_names:
                # 查找该产品是否有这个属性
                matching_prop = None
                for search_prop in product.properties:
                    if search_prop.property.property_name == prop_name:
                        matching_prop = search_prop
                        break

                if matching_prop is None:
                    # 该产品没有这个属性，匹配度为0
                    scores.append(0.0)
                else:
                    # 直接使用已经计算好的match_score
                    scores.append(
                        matching_prop.match_score
                        if matching_prop.match_score is not None
                        else 0.0
                    )

            product_scores[product.product_spec] = scores

        return product_scores

    def draw_match_radar(self, products: List[Product]) -> str:
        """
        绘制匹配雷达图，展示每个产品在各属性维度上的匹配度

        参数:
            products: 搜索得到的产品列表

        返回:
            str: base64编码的PNG图像
        """
        if not products:
            return ""

        # 1. 收集所有属性名称（用于雷达图的维度）
        all_property_names = set()
        for product in products:
            for search_prop in product.properties:
                all_property_names.add(search_prop.property.property_name)

        # 转为有序列表
        property_names = sorted(list(all_property_names))
        num_properties = len(property_names)

        if num_properties == 0:
            return ""

        # 2. 获取每个产品各属性维度的匹配分数
        product_scores = self._get_product_dimension_scores(products, property_names)

        # 3. 绘制雷达图
        fig, ax = plt.subplots(figsize=(10, 8), subplot_kw=dict(projection="polar"))

        # 计算每个属性的角度
        angles = np.linspace(0, 2 * np.pi, num_properties, endpoint=False).tolist()
        # 闭合雷达图
        angles += angles[:1]

        # 为每个产品绘制雷达线
        colors = plt.cm.get_cmap("Set3")(np.linspace(0, 1, len(products)))

        for idx, (product_spec, scores) in enumerate(product_scores.items()):
            # 闭合数据
            scores_closed = scores + scores[:1]

            ax.plot(
                angles,
                scores_closed,
                "o-",
                linewidth=2,
                label=product_spec,
                color=colors[idx],
            )
            ax.fill(angles, scores_closed, alpha=0.15, color=colors[idx])

        # 设置属性名称标签
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(property_names, fontsize=10)

        # 设置Y轴范围和标签
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])

        # 添加网格
        ax.grid(True, linestyle="--", alpha=0.7)

        # 添加图例
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)

        # 添加标题 - 设置中文字体支持
        try:
            # 尝试使用中文字体
            plt.rcParams["font.sans-serif"] = [
                "SimHei",
                "DejaVu Sans",
                "Arial Unicode MS",
            ]
            plt.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass

        plt.title("Product Match", fontsize=14, pad=20)

        # 调整布局
        plt.tight_layout()

        # 5. 转换为base64编码
        buffer = BytesIO()
        plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.read()).decode("utf-8")
        buffer.close()
        plt.close(fig)

        return image_base64

    def _calculate_match_score(
        self, target_value: Optional[float], lb: Optional[float], ub: Optional[float]
    ) -> float:
        """
        计算属性值的匹配分数

        匹配规则：
        - 如果target_value完全被[lb, ub]覆盖，匹配度100%
        - 如果target_value被lb或ub一侧覆盖（单边界），匹配度100%
        - 如果target_value游离在[lb, ub]外，匹配度根据差值比例计算

        参数:
            target_value: 产品的属性值
            lb: 搜索下界
            ub: 搜索上界

        返回:
            float: 匹配分数（0-100）
        """
        # 如果target_value不存在，匹配度为0
        if target_value is None:
            return 0.0

        # 如果搜索条件为空（都是None），认为完全匹配
        if lb is None and ub is None:
            return 100.0

        # 情况1: 只有上界
        if lb is None and ub is not None:
            if target_value <= ub:
                return 100.0
            else:
                # 超出上界，计算差值比例
                diff_ratio = (target_value - ub) / ub
                # 匹配度随差值比例递减，最小为0
                score = max(0, 100 * (1 - diff_ratio))
                return score

        # 情况2: 只有下界
        if lb is not None and ub is None:
            if target_value >= lb:
                return 100.0
            else:
                # 低于下界，计算差值比例
                diff_ratio = (lb - target_value) / lb
                # 匹配度随差值比例递减，最小为0
                score = max(0, 100 * (1 - diff_ratio))
                return score

        # 情况3: 同时有上下界
        if lb is not None and ub is not None:
            if lb <= target_value <= ub:
                # 完全在范围内
                return 100.0
            elif target_value < lb:
                # 低于下界
                diff_ratio = (lb - target_value) / lb
                score = max(0, 100 * (1 - diff_ratio))
                return score
            else:  # target_value > ub
                # 超出上界
                diff_ratio = (target_value - ub) / ub
                score = max(0, 100 * (1 - diff_ratio))
                return score

        return 0.0

    def draw_product_PCA(
        self,
        total_thickness_lb: Optional[float] = None,
        total_thickness_ub: Optional[float] = None,
        colour: Optional[List[str]] = None,
        PA_SUS_open_side_lb: Optional[float] = None,
        PA_SUS_open_side_ub: Optional[float] = None,
        PA_SUS_covered_side_lb: Optional[float] = None,
        PA_SUS_covered_side_ub: Optional[float] = None,
        Remove_force_lb: Optional[float] = None,
        Remove_force_ub: Optional[float] = None,
        Holding_Power_lb: Optional[float] = None,
        Holding_Power_ub: Optional[float] = None,
        cover_coating_weight_lb: Optional[float] = None,
        cover_coating_weight_ub: Optional[float] = None,
        open_coating_weight_lb: Optional[float] = None,
        open_coating_weight_ub: Optional[float] = None,
        
        color_column: Optional[str] = "open_PA",
    ) -> str:
        """
        对产品进行PCA降维并绘制散点图

        参数：
            与approximate_product_search相同的搜索参数

        返回：
            str: base64编码的PNG图像
        """
        key_columns = [
            "Product_type",
            "total_thickness",
            "backing_colour",
            "open_PA",
            "cover_PA",
            "removable_force",
            "open_holding_power",
            "cover_holding_power",
            "cover_coating_weight",
            "open_coating_weight",
        ]
        colour_mapping = {
            "Transparent": -1,
            "Black": 0,
            "White": 1,
        }

        # 1. 准备数据
        df = self.df_product_extended.copy()

        # 定义参数到列名的映射（单列属性）
        param_to_column = {
            "total_thickness": (total_thickness_lb, total_thickness_ub),
            "open_PA": (PA_SUS_open_side_lb, PA_SUS_open_side_ub),
            "cover_PA": (PA_SUS_covered_side_lb, PA_SUS_covered_side_ub),
            "removable_force": (Remove_force_lb, Remove_force_ub),
            "cover_coating_weight": (cover_coating_weight_lb, cover_coating_weight_ub),
            "open_coating_weight": (open_coating_weight_lb, open_coating_weight_ub),
        }
        
        # 1.5 判断每个产品是否满足输入的属性范围（在PCA之前）
        # 创建一个布尔数组标记满足所有条件的产品
        satisfies_constraints = pd.Series([True] * len(df), index=df.index)
        
        # 处理颜色约束（backing_colour）
        # 注意：如果colour为None或空列表，则不应用颜色过滤，所有产品在颜色维度上都视为满足条件
        color_to_backing_colour = {
            "透明": "Transparent",
            "白色": "White",
            "蓝色": "Blue",
            "黑色": "Black",
        }
        if colour is not None and len(colour) > 0:
            # 将前端颜色输入映射为backing_colour列的值
            backing_colour_values = [color_to_backing_colour.get(c, c) for c in colour]
            
            # 检查backing_colour列是否存在
            if "backing_colour" in df.columns:
                # 只有在指定颜色列表中的产品才满足颜色约束
                colour_mask = df["backing_colour"].isin(backing_colour_values)
                satisfies_constraints &= colour_mask
        
        # 遍历每个属性，检查是否满足条件
        for col_name, (lb, ub) in param_to_column.items():
            # 如果lb和ub都为None，跳过该属性
            if lb is None and ub is None:
                continue
            
            # 如果该列不在df中，跳过
            if col_name not in df.columns:
                print(f"Warning: Column '{col_name}' not found in data, skipping...")
                continue
            
            # 检查该列的值是否满足条件
            col_values = df[col_name]
            
            if lb is not None and ub is not None:
                # 同时指定上下界
                # 空值认为满足条件，或者值在范围内
                mask = col_values.isna() | ((col_values >= lb) & (col_values <= ub))
            elif ub is not None:
                # 只指定上界
                # 空值认为满足条件，或者值小于等于上界
                mask = col_values.isna() | (col_values <= ub)
            else:
                # 只指定下界
                # 空值认为满足条件，或者值大于等于下界
                mask = col_values.isna() | (col_values >= lb)
            
            # 将满足条件的mask与总体mask进行AND操作
            satisfies_constraints &= mask
        
        # 特殊处理：Holding_Power 需要检查 open_holding_power 和 cover_holding_power 两列
        # 只要有一个满足条件即可（OR逻辑）
        if Holding_Power_lb is not None or Holding_Power_ub is not None:
            holding_power_mask = pd.Series([False] * len(df), index=df.index)
            
            for col_name in ["open_holding_power", "cover_holding_power"]:
                if col_name not in df.columns:
                    print(f"Warning: Column '{col_name}' not found in data, skipping...")
                    continue
                
                col_values = df[col_name]
                
                if Holding_Power_lb is not None and Holding_Power_ub is not None:
                    # 同时指定上下界
                    # 空值认为满足条件，或者值在范围内
                    col_mask = col_values.isna() | ((col_values >= Holding_Power_lb) & (col_values <= Holding_Power_ub))
                elif Holding_Power_ub is not None:
                    # 只指定上界
                    col_mask = col_values.isna() | (col_values <= Holding_Power_ub)
                else:
                    # 只指定下界
                    col_mask = col_values.isna() | (col_values >= Holding_Power_lb)
                
                # 对于holding power，使用OR逻辑：只要有一列满足条件即可
                holding_power_mask |= col_mask
            
            # 将holding_power_mask与总体mask进行AND操作
            satisfies_constraints &= holding_power_mask

        # 将backing_colour按照colour_mapping转换为数值
        if "backing_colour" in df.columns:
            df["backing_colour"] = df["backing_colour"].map(colour_mapping)

        # 选择key_columns中存在的列
        available_columns = [col for col in key_columns if col in df.columns]

        if not available_columns:
            return ""

        # 提取特征数据
        df_features = df[available_columns].copy()

        # 缺失数据用-1填充
        df_features = df_features.fillna(-1)

        # 2. 标准化数据
        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(df_features)

        # 3. PCA降维到2维
        pca = PCA(n_components=2)
        features_pca = pca.fit_transform(features_scaled)

        # 4. 绘制散点图和等高线
        fig, ax = plt.subplots(figsize=(10, 8))

        # 创建网格用于绘制等高线
        x_min, x_max = features_pca[:, 0].min() - 1, features_pca[:, 0].max() + 1
        y_min, y_max = features_pca[:, 1].min() - 1, features_pca[:, 1].max() + 1

        # 创建网格点
        xx, yy = np.meshgrid(
            np.linspace(x_min, x_max, 100), np.linspace(y_min, y_max, 100)
        )

        # 计算每个网格点的密度（使用高斯核密度估计）
        from scipy.stats import gaussian_kde

        # 计算每个散点位置的密度值用于着色
        point_densities = None
        if len(features_pca) > 1:
            # 构建核密度估计
            kde = gaussian_kde(features_pca.T)
            # 计算网格上的密度（用于等高线）
            grid_points = np.c_[xx.ravel(), yy.ravel()]
            density = kde(grid_points.T).reshape(xx.shape)
            
            # 计算每个散点位置的密度值
            point_densities = kde(features_pca.T)

            # 绘制等高线 - 使用浅灰色线条
            ax.contour(
                xx, yy, density, levels=8, colors="lightgray", alpha=0.4, linewidths=0.8
            )
            # 填充等高线 - 使用浅灰色配色方案
            # 使用固定的vmin和vmax确保等高线颜色深浅一致
            density_vmin = 0
            density_vmax = np.max(density)
            ax.contourf(xx, yy, density, levels=8, cmap="Greys", alpha=0.08, vmin=density_vmin, vmax=density_vmax)

        # 根据color_column对点进行着色
        use_numeric_coloring = False
        if color_column and color_column in df.columns:
            color_values = df[color_column].values
            
            # 检查color_column是否为数值类型
            try:
                numeric_series = pd.to_numeric(pd.Series(color_values), errors='coerce')
                numeric_values = np.array(numeric_series.values, dtype=float)
                
                # 如果超过50%的值能转换为数值，则视为数值列
                if np.count_nonzero(~np.isnan(numeric_values)) / len(numeric_values) > 0.5:
                    # 数值类型：使用颜色渐变映射（数值越大颜色越深）
                    use_numeric_coloring = True
                    
                    # 计算所有数据点的范围（在绘制之前）
                    vmin = np.nanmin(numeric_values)
                    vmax = np.nanmax(numeric_values)
                    
                    # 分别绘制满足条件和不满足条件的点
                    # 先绘制不满足条件的点（在下层）
                    satisfied_mask_values = np.array(satisfies_constraints.values, dtype=bool)
                    unsatisfied_mask = ~satisfied_mask_values
                    scatter_unsatisfied = None
                    if np.any(unsatisfied_mask):
                        scatter_unsatisfied = ax.scatter(
                            features_pca[unsatisfied_mask, 0],
                            features_pca[unsatisfied_mask, 1],
                            c=numeric_values[unsatisfied_mask],
                            cmap="viridis_r",
                            alpha=0.4,
                            s=60,
                            edgecolors="gray",
                            linewidths=0.8,
                            vmin=vmin,
                            vmax=vmax,
                        )
                    
                    # 再绘制满足条件的点（在上层，用圆圈突出显示）
                    satisfied_mask = satisfied_mask_values
                    scatter = None
                    if np.any(satisfied_mask):
                        scatter = ax.scatter(
                            features_pca[satisfied_mask, 0],
                            features_pca[satisfied_mask, 1],
                            c=numeric_values[satisfied_mask],
                            cmap="viridis_r",
                            alpha=0.9,
                            s=120,
                            edgecolors="red",
                            linewidths=2.5,
                            marker="o",
                            label="Satisfies Constraints",
                            vmin=vmin,
                            vmax=vmax,
                        )
                        # 添加图例
                        ax.legend(loc="upper right", fontsize=10)
                    
                    # 添加颜色条到图片右侧（始终显示）
                    # 创建一个独立的ScalarMappable来确保colorbar显示完整的颜色范围
                    from matplotlib.cm import ScalarMappable
                    from matplotlib.colors import Normalize
                    
                    norm = Normalize(vmin=vmin, vmax=vmax)
                    sm = ScalarMappable(cmap="viridis_r", norm=norm)
                    sm.set_array([])  # 必须调用set_array才能创建colorbar
                    
                    cbar = plt.colorbar(sm, ax=ax)
                    cbar.set_label(color_column, fontsize=10)
            except (ValueError, TypeError):
                pass  # 如果转换失败，使用默认着色方式
        
        # 如果没有使用数值着色，则使用密度值进行着色
        if not use_numeric_coloring:
            if point_densities is not None:
                # 计算所有数据点的密度范围（在绘制之前）
                vmin = np.min(point_densities)
                vmax = np.max(point_densities)
                
                # 分别绘制满足条件和不满足条件的点
                # 先绘制不满足条件的点（在下层）
                satisfied_mask_values = np.array(satisfies_constraints.values, dtype=bool)
                unsatisfied_mask = ~satisfied_mask_values
                scatter_unsatisfied = None
                if np.any(unsatisfied_mask):
                    scatter_unsatisfied = ax.scatter(
                        features_pca[unsatisfied_mask, 0],
                        features_pca[unsatisfied_mask, 1],
                        c=point_densities[unsatisfied_mask],
                        cmap="viridis",
                        alpha=0.4,
                        s=60,
                        edgecolors="gray",
                        linewidths=0.8,
                        vmin=vmin,
                        vmax=vmax,
                    )
                
                # 再绘制满足条件的点（在上层，用圆圈突出显示）
                satisfied_mask = satisfied_mask_values
                scatter = None
                if np.any(satisfied_mask):
                    scatter = ax.scatter(
                        features_pca[satisfied_mask, 0],
                        features_pca[satisfied_mask, 1],
                        c=point_densities[satisfied_mask],
                        cmap="viridis",
                        alpha=0.9,
                        s=120,
                        edgecolors="red",
                        linewidths=2.5,
                        marker="o",
                        label="Satisfies Constraints",
                        vmin=vmin,
                        vmax=vmax,
                    )
                    # 添加图例
                    ax.legend(loc="upper right", fontsize=10)
                
                # 添加颜色条到图片右侧（始终显示）
                # 创建一个独立的ScalarMappable来确保colorbar显示完整的颜色范围
                from matplotlib.cm import ScalarMappable
                from matplotlib.colors import Normalize
                
                norm = Normalize(vmin=vmin, vmax=vmax)
                sm = ScalarMappable(cmap="viridis", norm=norm)
                sm.set_array([])  # 必须调用set_array才能创建colorbar
                
                cbar = plt.colorbar(sm, ax=ax)
                cbar.set_label("Density", fontsize=10)
            else:
                # 如果无法计算密度，使用默认颜色
                # 分别绘制满足条件和不满足条件的点
                satisfied_mask_values = np.array(satisfies_constraints.values, dtype=bool)
                unsatisfied_mask = ~satisfied_mask_values
                if np.any(unsatisfied_mask):
                    ax.scatter(
                        features_pca[unsatisfied_mask, 0],
                        features_pca[unsatisfied_mask, 1],
                        c="lightblue",
                        alpha=0.4,
                        s=60,
                        edgecolors="gray",
                        linewidths=0.8,
                    )
                
                satisfied_mask = satisfied_mask_values
                if np.any(satisfied_mask):
                    ax.scatter(
                        features_pca[satisfied_mask, 0],
                        features_pca[satisfied_mask, 1],
                        c="lightblue",
                        alpha=0.9,
                        s=120,
                        edgecolors="red",
                        linewidths=2.5,
                        marker="o",
                        label="Satisfies Constraints"
                    )
                    ax.legend(loc="upper right", fontsize=10)

        # 设置标题和标签
        ax.set_xlabel(
            f"PC1 ({pca.explained_variance_ratio_[0]:.2%} variance)",
            fontsize=12,
        )
        ax.set_ylabel(
            f"PC2 ({pca.explained_variance_ratio_[1]:.2%} variance)",
            fontsize=12,
        )
        ax.set_title(
            "Product PCA Visualization with Density Contours", fontsize=14, pad=20
        )

        # 添加网格
        ax.grid(True, linestyle="--", alpha=0.3)

        # 调整布局
        plt.tight_layout()

        # 5. 转换为base64编码
        buffer = BytesIO()
        plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.read()).decode("utf-8")
        buffer.close()
        plt.close(fig)

        return image_base64
