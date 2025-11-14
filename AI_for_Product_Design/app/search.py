from pydantic import BaseModel
from typing import List, Optional, Union
import pandas as pd
from pathlib import Path
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
    name: str  # 属性名称
    description: Optional[str] = None  # 属性描述
    lb: Optional[float] = None  # 属性值下界
    ub: Optional[float] = None  # 属性值上界
    value: Optional[str] = None  # 属性值，针对属性值不是数值类型的属性，例如颜色
    test_method: Optional[str] = None  # 测试方法
    is_search_criteria: bool = False  # 是否是搜索条件中使用的核心属性

class Product(BaseModel):
    NART: str  # 胶带产品id
    product_type: str  # 产品类型: double_liner, single_liner
    Liner_NART: Optional[str] = None  # liner部分的liner NART
    In_Liner_NART: Optional[str] = None  # in_liner 部分使用的liner NART
    Out_Liner_NART: Optional[str] = None  # out_liner 部分使用的liner NART
    Open_Adhesive_NART: Optional[str] = None  # open side 使用的adhesive NART
    Cover_Adhesive_NART: Optional[str] = None  # cover side 使用的adhesive NART
    Backing_NART: Optional[str] = None  # backing部分使用的NART
    labels: List[str] = []  # 产品标签列表，对应 L1 和 L2
    properties: List[Property]  # 属性列表

class Adhesive(BaseModel):
    NART: str  # adhesive NART
    properties: List[Property]  # 属性列表

class Liner(BaseModel):
    NART: str  # liner NART
    properties: List[Property]  # 属性列表

class Backing(BaseModel):
    NART: str  # backing NART
    properties: List[Property]  # 属性列表

class ProductSearch:
    """
    A class for searching products based on various properties.
    """
    # 浮点数比较的容差值，用于处理浮点数精度问题
    FLOAT_TOLERANCE = 1e-9

    def __init__(self):
        """
        Initializes the ProductSearch class by loading product and material tables.
        """

        self.df_product = pd.read_csv(BASE_DIR / 'data/df_product.csv', sep='|')
        self.df_product_extended = pd.read_csv(BASE_DIR / 'data/df_product_extended.csv', sep='|')
        self.df_adhesive = pd.read_csv(BASE_DIR / 'data/df_adhesive_properties.csv', sep='|')
        self.df_liner = pd.read_csv(BASE_DIR / 'data/df_liner_properties.csv', sep='|')
        self.df_backing = pd.read_csv(BASE_DIR / 'data/df_backing_properties.csv', sep='|')
        self.df_item_no = pd.read_csv(BASE_DIR / 'data/item_no_name_mapping.csv', sep='|')

        # Create a mapping dictionary for quick lookup: Item_No -> Item_Name
        self.item_name_mapping = dict(zip(self.df_item_no['Item_No'], self.df_item_no['Item_Name']))

    def search_products(
        self,
        total_thickness_lb: Optional[float],
        total_thickness_ub: Optional[float],
        colour: str,
        backing_material: str,
        PA_SUS_open_side_lb: Optional[float],
        PA_SUS_open_side_ub: Optional[float],
        PA_SUS_covered_side_lb: Optional[float],
        PA_SUS_covered_side_ub: Optional[float],
        Remove_force_lb: Optional[float],
        Remove_force_ub: Optional[float],
        label: Optional[str] = None,
        order_by: Optional[str] = None,
        order_direction: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Product]:
        """
        根据给定的筛选条件搜索产品。

        参数：
            product_type (int): 产品类型。1, 双面胶
            total_thickness_lb (float): 胶带总厚度的下界。
            total_thickness_ub (float): 胶带总厚度的上界。
            colour (str): 胶带 Backing 的颜色。
            backing_material (str): 胶带基材的材料。
            PA_SUS_open_side_lb (float): open面不锈钢剥离力的下界。
            PA_SUS_open_side_ub (float): open面不锈钢剥离力的上界。
            PA_SUS_covered_side_lb (float): cover面不锈钢剥离力的下界。
            PA_SUS_covered_side_ub (float): cover面不锈钢剥离力的上界。
            Remove_force_lb (float): 离型纸剥离力的下界。
            Remove_force_ub (float): 离型纸剥离力的上界。

        返回：
            满足条件的产品列表。
        """
        # 不同产品对应的open side pa item no
        open_side_pa_item_no_by_product_type = {
            0: ['P4005'],
            1: ['P4144'],
        }
        
        # 不同产品对应的cover side pa item no
        cover_side_pa_item_no_by_product_type = {
            0: ["P4006"],
            1: ["P4145"],
        }

        # removable force 对应的item no
        removable_force_item_nos = [
            'P4004', 'P4127', 'P4140', 'P4141', 'P4169', 'P4170',
        ]

        # 将前端输入的color映射为property 搜索的关键词
        color_keyword_mapping = {
            "透明": "transparent",
            "白色": "white",
            "蓝色": "blue",
        }

        # 记录使用的搜索条件对应的属性名称（用于前端高亮显示）
        search_criteria_properties = set()

        # 添加使用的搜索条件
        if total_thickness_lb is not None or total_thickness_ub is not None:
            search_criteria_properties.add('P4433')  # total thickness

        if PA_SUS_open_side_lb is not None or PA_SUS_open_side_ub is not None:
            # 添加所有可能的 open side PA item nos
            for item_nos in open_side_pa_item_no_by_product_type.values():
                search_criteria_properties.update(item_nos)

        if PA_SUS_covered_side_lb is not None or PA_SUS_covered_side_ub is not None:
            # 添加所有可能的 cover side PA item nos
            for item_nos in cover_side_pa_item_no_by_product_type.values():
                search_criteria_properties.update(item_nos)

        if Remove_force_lb is not None or Remove_force_ub is not None:
            search_criteria_properties.update(removable_force_item_nos)

        # Start with all products in extended dataframe
        df = self.df_product_extended.copy()
        
        # Filter by total thickness (P4433)
        if total_thickness_lb is not None or total_thickness_ub is not None:
            target_value_col = 'P4433_target_value'

            if total_thickness_lb is not None and total_thickness_ub is not None:
                # Both bounds specified: lb <= target_value <= ub
                # 使用容差处理浮点数精度问题
                mask = (
                    (df[target_value_col].notna()) &
                    (df[target_value_col] >= total_thickness_lb - self.FLOAT_TOLERANCE) &
                    (df[target_value_col] <= total_thickness_ub + self.FLOAT_TOLERANCE)
                )
            elif total_thickness_ub is not None:
                # Only upper bound: target_value <= ub
                mask = (
                    (df[target_value_col].notna()) &
                    (df[target_value_col] <= total_thickness_ub + self.FLOAT_TOLERANCE)
                )
            else:
                # Only lower bound: target_value >= lb
                mask = (
                    (df[target_value_col].notna()) &
                    (df[target_value_col] >= total_thickness_lb - self.FLOAT_TOLERANCE)
                )
            df = df[mask]
        
        # Filter by backing material
        # TODO: 更改backing 材料的检索条件
        if backing_material is not None and backing_material != "":
            df = df[df['Backing_NART'] == backing_material]
        
        # Filter by colour (backing colour)
        if colour is not None and colour != "":
            # Map frontend colour input to search keyword
            colour_keyword = color_keyword_mapping.get(colour, colour.lower())

            # Find all backings that have the specified colour
            # Search in df_backing for property_key containing 'colour' or 'color'
            backing_colour_records = self.df_backing[
                self.df_backing['property_key'].str.contains('colour|color', case=False, na=False)
            ]

            # Filter backings by the colour value (case-insensitive search in property_value)
            matching_backings = backing_colour_records[
                backing_colour_records['property_value'].str.contains(colour_keyword, case=False, na=False)
            ]['Backing'].unique()

            # Filter products that have a matching backing
            df = df[df['Backing_NART'].isin(matching_backings)]
        
        # Filter by PA SUS open side
        if PA_SUS_open_side_lb is not None or PA_SUS_open_side_ub is not None:
            # Check all possible open side PA item nos across all product types
            all_open_side_item_nos = []
            for item_nos in open_side_pa_item_no_by_product_type.values():
                all_open_side_item_nos.extend(item_nos)

            combined_mask = pd.Series([False] * len(df), index=df.index)
            for item_no in all_open_side_item_nos:
                target_value_col = f'{item_no}_target_value'

                # Skip if column doesn't exist
                if target_value_col not in df.columns:
                    continue

                if PA_SUS_open_side_lb is not None and PA_SUS_open_side_ub is not None:
                    # Both bounds specified: lb <= target_value <= ub
                    # 使用容差处理浮点数精度问题
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] >= PA_SUS_open_side_lb - self.FLOAT_TOLERANCE) &
                        (df[target_value_col] <= PA_SUS_open_side_ub + self.FLOAT_TOLERANCE)
                    )
                elif PA_SUS_open_side_ub is not None:
                    # Only upper bound: target_value <= ub
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] <= PA_SUS_open_side_ub + self.FLOAT_TOLERANCE)
                    )
                else:
                    # Only lower bound: target_value >= lb
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] >= PA_SUS_open_side_lb - self.FLOAT_TOLERANCE)
                    )
                combined_mask = combined_mask | mask

            df = df[combined_mask]
        
        # Filter by PA SUS covered side
        if PA_SUS_covered_side_lb is not None or PA_SUS_covered_side_ub is not None:
            # Check all possible cover side PA item nos across all product types
            all_cover_side_item_nos = []
            for item_nos in cover_side_pa_item_no_by_product_type.values():
                all_cover_side_item_nos.extend(item_nos)

            combined_mask = pd.Series([False] * len(df), index=df.index)
            for item_no in all_cover_side_item_nos:
                target_value_col = f'{item_no}_target_value'

                # Skip if column doesn't exist
                if target_value_col not in df.columns:
                    continue

                if PA_SUS_covered_side_lb is not None and PA_SUS_covered_side_ub is not None:
                    # Both bounds specified: lb <= target_value <= ub
                    # 使用容差处理浮点数精度问题
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] >= PA_SUS_covered_side_lb - self.FLOAT_TOLERANCE) &
                        (df[target_value_col] <= PA_SUS_covered_side_ub + self.FLOAT_TOLERANCE)
                    )
                elif PA_SUS_covered_side_ub is not None:
                    # Only upper bound: target_value <= ub
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] <= PA_SUS_covered_side_ub + self.FLOAT_TOLERANCE)
                    )
                else:
                    # Only lower bound: target_value >= lb
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] >= PA_SUS_covered_side_lb - self.FLOAT_TOLERANCE)
                    )
                combined_mask = combined_mask | mask

            df = df[combined_mask]
        
        # Filter by removal force
        # Check all removable force item nos and keep products that match any of them
        if Remove_force_lb is not None or Remove_force_ub is not None:
            combined_mask = pd.Series([False] * len(df), index=df.index)

            for item_no in removable_force_item_nos:
                target_value_col = f'{item_no}_target_value'

                # Skip if column doesn't exist
                if target_value_col not in df.columns:
                    continue

                if Remove_force_lb is not None and Remove_force_ub is not None:
                    # Both bounds specified: lb <= target_value <= ub
                    # 使用容差处理浮点数精度问题
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] >= Remove_force_lb - self.FLOAT_TOLERANCE) &
                        (df[target_value_col] <= Remove_force_ub + self.FLOAT_TOLERANCE)
                    )
                elif Remove_force_ub is not None:
                    # Only upper bound: target_value <= ub
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] <= Remove_force_ub + self.FLOAT_TOLERANCE)
                    )
                else:
                    # Only lower bound: target_value >= lb
                    mask = (
                        (df[target_value_col].notna()) &
                        (df[target_value_col] >= Remove_force_lb - self.FLOAT_TOLERANCE)
                    )
                combined_mask = combined_mask | mask

            df = df[combined_mask]

        # Filter by label (L1 or L2)
        if label is not None and label != "":
            # Check if the label appears in either L1 or L2 column
            mask = (
                (df['L1'].notna() & df['L1'].str.contains(label, case=False, na=False)) |
                (df['L2'].notna() & df['L2'].str.contains(label, case=False, na=False))
            )
            df = df[mask]
        
        # Convert filtered dataframe to Product objects
        product_list = []
        for _, row in df.iterrows():
            # Extract properties from the row
            properties = []
            product_spec = row['Product_Spec']

            # Add all properties that have values
            for col in df.columns:
                if col.startswith('P') and col.endswith('_target_value'):
                    item_no = col.replace('_target_value', '')
                    if pd.notna(row[col]):
                        # Query df_product for property_value, test_method, and description
                        # Filter by Product Spec and Item No.
                        product_records = self.df_product[
                            (self.df_product['Product Spec'] == product_spec) &
                            (self.df_product['Item No.'] == item_no)
                        ]

                        property_value = None
                        test_method = None
                        description = None

                        if len(product_records) > 0:
                            # Get the first matching record
                            record = product_records.iloc[0]
                            property_value = record.get('property_value')
                            test_method = record.get('Test Method')
                            # Get description from df_product (Item Description column)
                            description = record.get('Item Description')

                            # Convert to string if not None
                            if pd.notna(property_value):
                                property_value = str(property_value)
                            else:
                                property_value = None

                            if pd.notna(test_method):
                                test_method = str(test_method)
                            else:
                                test_method = None

                            if pd.notna(description):
                                description = str(description)
                            else:
                                description = None

                        # Fallback to item_name_mapping if description not found in df_product
                        if description is None:
                            description = self.item_name_mapping.get(item_no)

                        # 检查该属性是否是搜索条件中使用的核心属性
                        is_search_criteria = item_no in search_criteria_properties

                        properties.append(Property(
                            name=item_no,
                            description=description,
                            lb=row.get(f'{item_no}_lb'),
                            ub=row.get(f'{item_no}_ub'),
                            value=property_value,
                            test_method=test_method,
                            is_search_criteria=is_search_criteria
                        ))

            # Extract labels from L1 and L2 columns
            labels = []
            if pd.notna(row.get('L1')) and row.get('L1') != '':
                labels.append(str(row.get('L1')))
            if pd.notna(row.get('L2')) and row.get('L2') != '':
                labels.append(str(row.get('L2')))

            # Create product object
            product = Product(
                NART=row['Product_Spec'],
                product_type='double_liner' if row['Product_type'] == 1 else 'single_liner',
                Liner_NART=row.get('Liner_NART') if pd.notna(row.get('Liner_NART')) else None,
                In_Liner_NART=row.get('In_Liner_NART') if pd.notna(row.get('In_Liner_NART')) else None,
                Out_Liner_NART=row.get('Out_Liner_NART') if pd.notna(row.get('Out_Liner_NART')) else None,
                Open_Adhesive_NART=row.get('Open_Adhesive_NART') if pd.notna(row.get('Open_Adhesive_NART')) else None,
                Cover_Adhesive_NART=row.get('Cover_Adhesive_NART') if pd.notna(row.get('Cover_Adhesive_NART')) else None,
                Backing_NART=row.get('Backing_NART') if pd.notna(row.get('Backing_NART')) else None,
                labels=labels,
                properties=properties
            )
            product_list.append(product)

        # 排序处理
        if order_by and order_direction and product_list:
            # 确定排序方向
            reverse = (order_direction.lower() == 'desc')

            # 使用已加载的 df_product 获取 target_value
            # 创建一个字典：{Product_Spec: {Item_No: target_value}}
            target_value_map = {}
            for _, row in self.df_product.iterrows():
                product_spec = row.get('Product Spec')
                item_no = row.get('Item No.')
                target_value = row.get('target_value')

                if pd.notna(product_spec) and pd.notna(item_no):
                    if product_spec not in target_value_map:
                        target_value_map[product_spec] = {}
                    if pd.notna(target_value) and target_value != '':
                        try:
                            target_value_map[product_spec][item_no] = float(target_value)
                        except (ValueError, TypeError):
                            pass

            # 定义排序函数
            def get_target_value(product: Product) -> float:
                product_spec = product.NART
                if product_spec in target_value_map and order_by in target_value_map[product_spec]:
                    return target_value_map[product_spec][order_by]
                # 如果没有这个属性，返回 inf，排在最后
                return float('inf')

            product_list.sort(key=get_target_value, reverse=reverse)

        # 应用 limit
        if limit is not None and limit > 0:
            product_list = product_list[:limit]

        return product_list

    def search_materials(
        self,
        material_type: str, 
        total_thickness_lb: Optional[float] = None,
        total_thickness_ub: Optional[float] = None,
        colour: Optional[str] = None,
        tensile_strength_MD_lb: Optional[float] = None,
        tensile_strength_MD_ub: Optional[float] = None,
        tensile_strength_CD_lb: Optional[float] = None,
        tensile_strength_CD_ub: Optional[float] = None,
        shrinkage_MD_lb: Optional[float] = None, 
        shrinkage_MD_ub: Optional[float] = None,
        shrinkage_CD_lb: Optional[float] = None,
        shrinkage_CD_ub: Optional[float] = None,
    ) -> List[Adhesive|Backing|Liner]:
        """
        Searches for materials based on the given criteria.
        
        Args:
            material_type (str): 材料类型，可选值: "Adhesive", "Liner", "Backing"
            total_thickness_lb (float, optional): 厚度的下界
            total_thickness_ub (float, optional): 厚度的上界
            colour (str, optional): 颜色 (仅适用于Liner)
            tensile_strength_MD_lb (float, optional): MD方向拉伸强度的下界 (适用于Backing 和 Liner)
            tensile_strength_MD_ub (float, optional): MD方向拉伸强度的上界 (适用于Backing 和 Liner)
            tensile_strength_CD_lb (float, optional): CD方向拉伸强度的下界 (适用于Backing 和 Liner)
            tensile_strength_CD_ub (float, optional): CD方向拉伸强度的上界 (适用于Backing 和 Liner)
            shrinkage_MD_lb (float, optional): MD方向收缩率的下界 (适用于Backing 和 Liner)
            shrinkage_MD_ub (float, optional): MD方向收缩率的上界 (适用于Backing 和 Liner)
            shrinkage_CD_lb (float, optional): CD方向收缩率的下界 (适用于Backing 和 Liner)
            shrinkage_CD_ub (float, optional): CD方向收缩率的上界 (适用于Backing 和 Liner)
            
        Returns:
            A list of materials (Adhesive, Liner, or Backing) that match the criteria.
        """
        # 将前端输入的color映射为property 搜索的关键词
        color_keyword_mapping = {
            "透明": "transparent",
            "白色": "white",
            "蓝色": "blue",
        }

        # 记录使用的搜索条件对应的属性名称（用于前端高亮显示）
        # 对于材料，我们记录 property_key 的模式（如 "thickness", "colour", "tensile strength md" 等）
        search_criteria_property_patterns = set()

        if total_thickness_lb is not None or total_thickness_ub is not None:
            search_criteria_property_patterns.add('thickness')

        if colour is not None and colour != "":
            search_criteria_property_patterns.add('colour')

        if tensile_strength_MD_lb is not None or tensile_strength_MD_ub is not None:
            search_criteria_property_patterns.add('tensile.*md')

        if tensile_strength_CD_lb is not None or tensile_strength_CD_ub is not None:
            search_criteria_property_patterns.add('tensile.*cd')

        if shrinkage_MD_lb is not None or shrinkage_MD_ub is not None:
            search_criteria_property_patterns.add('shrinkage.*md')

        if shrinkage_CD_lb is not None or shrinkage_CD_ub is not None:
            search_criteria_property_patterns.add('shrinkage.*cd')

        # 根据material_type选择对应的dataframe和NART列名
        if material_type.lower() == "adhesive":
            df = self.df_adhesive.copy()
            nart_col = 'Adhesive'
            material_class = Adhesive
        elif material_type.lower() == "liner":
            df = self.df_liner.copy()
            nart_col = 'Liner'
            material_class = Liner
        elif material_type.lower() == "backing":
            df = self.df_backing.copy()
            nart_col = 'Backing'
            material_class = Backing
        else:
            raise ValueError(f"Invalid material_type: {material_type}. Must be 'Adhesive', 'Liner', or 'Backing'")

        # Get unique NARTs
        narts = df[nart_col].unique()
        matching_narts = set(narts)
        
        # Filter by thickness
        if total_thickness_lb is not None or total_thickness_ub is not None:
            thickness_records = df[
                df['property_key'].str.contains('thickness', case=False, na=False)
            ]

            # Find materials using target_value
            matching_thickness_narts = set()
            for nart in narts:
                nart_records = thickness_records[thickness_records[nart_col] == nart]
                if len(nart_records) > 0:
                    for _, record in nart_records.iterrows():
                        target_value = record.get('target_value')
                        if pd.notna(target_value):
                            # Apply the same logic as search_products
                            # 使用容差处理浮点数精度问题
                            if total_thickness_lb is not None and total_thickness_ub is not None:
                                # Both bounds: lb <= target_value <= ub
                                if (total_thickness_lb - self.FLOAT_TOLERANCE) <= target_value <= (total_thickness_ub + self.FLOAT_TOLERANCE):
                                    matching_thickness_narts.add(nart)
                                    break
                            elif total_thickness_ub is not None:
                                # Only upper bound: target_value <= ub
                                if target_value <= (total_thickness_ub + self.FLOAT_TOLERANCE):
                                    matching_thickness_narts.add(nart)
                                    break
                            else:
                                # Only lower bound: target_value >= lb
                                if target_value >= (total_thickness_lb - self.FLOAT_TOLERANCE):
                                    matching_thickness_narts.add(nart)
                                    break

            matching_narts &= matching_thickness_narts
        
        # Filter by colour (for Backing and Liner)
        if colour is not None and colour != "" and material_type.lower() in ("backing", "liner"):
            colour_keyword = color_keyword_mapping.get(colour, colour.lower())

            colour_records = df[
                df['property_key'].str.contains('colour|color', case=False, na=False)
            ]

            matching_colour_narts = set(
                colour_records[
                    colour_records['property_value'].str.contains(colour_keyword, case=False, na=False)
                ][nart_col].unique()
            )

            matching_narts &= matching_colour_narts
        
        # Filter by tensile strength MD (适用于 Backing 和 Liner)
        if (tensile_strength_MD_lb is not None or tensile_strength_MD_ub is not None) and material_type.lower() in ("backing", "liner"):
            ts_md_records = df[
                df['property_key'].str.contains('tensile.*md', case=False, na=False, regex=True)
            ]

            matching_ts_md_narts = set()
            for nart in narts:
                nart_records = ts_md_records[ts_md_records[nart_col] == nart]
                if len(nart_records) > 0:
                    for _, record in nart_records.iterrows():
                        target_value = record.get('target_value')
                        if pd.notna(target_value):
                            # Apply the same logic as search_products
                            # 使用容差处理浮点数精度问题
                            if tensile_strength_MD_lb is not None and tensile_strength_MD_ub is not None:
                                # Both bounds: lb <= target_value <= ub
                                if (tensile_strength_MD_lb - self.FLOAT_TOLERANCE) <= target_value <= (tensile_strength_MD_ub + self.FLOAT_TOLERANCE):
                                    matching_ts_md_narts.add(nart)
                                    break
                            elif tensile_strength_MD_ub is not None:
                                # Only upper bound: target_value <= ub
                                if target_value <= (tensile_strength_MD_ub + self.FLOAT_TOLERANCE):
                                    matching_ts_md_narts.add(nart)
                                    break
                            else:
                                # Only lower bound: target_value >= lb
                                if target_value >= (tensile_strength_MD_lb - self.FLOAT_TOLERANCE):
                                    matching_ts_md_narts.add(nart)
                                    break

            matching_narts &= matching_ts_md_narts
        
        # Filter by tensile strength CD (适用于 Backing 和 Liner)
        if (tensile_strength_CD_lb is not None or tensile_strength_CD_ub is not None) and material_type.lower() in ("backing", "liner"):
            ts_cd_records = df[
                df['property_key'].str.contains('tensile.*cd', case=False, na=False, regex=True)
            ]

            matching_ts_cd_narts = set()
            for nart in narts:
                nart_records = ts_cd_records[ts_cd_records[nart_col] == nart]
                if len(nart_records) > 0:
                    for _, record in nart_records.iterrows():
                        target_value = record.get('target_value')
                        if pd.notna(target_value):
                            # Apply the same logic as search_products
                            # 使用容差处理浮点数精度问题
                            if tensile_strength_CD_lb is not None and tensile_strength_CD_ub is not None:
                                # Both bounds: lb <= target_value <= ub
                                if (tensile_strength_CD_lb - self.FLOAT_TOLERANCE) <= target_value <= (tensile_strength_CD_ub + self.FLOAT_TOLERANCE):
                                    matching_ts_cd_narts.add(nart)
                                    break
                            elif tensile_strength_CD_ub is not None:
                                # Only upper bound: target_value <= ub
                                if target_value <= (tensile_strength_CD_ub + self.FLOAT_TOLERANCE):
                                    matching_ts_cd_narts.add(nart)
                                    break
                            else:
                                # Only lower bound: target_value >= lb
                                if target_value >= (tensile_strength_CD_lb - self.FLOAT_TOLERANCE):
                                    matching_ts_cd_narts.add(nart)
                                    break

            matching_narts &= matching_ts_cd_narts
        
        # Filter by shrinkage MD (适用于 Backing 和 Liner)
        if (shrinkage_MD_lb is not None or shrinkage_MD_ub is not None) and material_type.lower() in ("backing", "liner"):
            shrinkage_md_records = df[
                df['property_key'].str.contains('shrinkage.*md', case=False, na=False, regex=True)
            ]

            matching_shrinkage_md_narts = set()
            for nart in narts:
                nart_records = shrinkage_md_records[shrinkage_md_records[nart_col] == nart]
                if len(nart_records) > 0:
                    for _, record in nart_records.iterrows():
                        target_value = record.get('target_value')
                        if pd.notna(target_value):
                            # Apply the same logic as search_products
                            # 使用容差处理浮点数精度问题
                            if shrinkage_MD_lb is not None and shrinkage_MD_ub is not None:
                                # Both bounds: lb <= target_value <= ub
                                if (shrinkage_MD_lb - self.FLOAT_TOLERANCE) <= target_value <= (shrinkage_MD_ub + self.FLOAT_TOLERANCE):
                                    matching_shrinkage_md_narts.add(nart)
                                    break
                            elif shrinkage_MD_ub is not None:
                                # Only upper bound: target_value <= ub
                                if target_value <= (shrinkage_MD_ub + self.FLOAT_TOLERANCE):
                                    matching_shrinkage_md_narts.add(nart)
                                    break
                            else:
                                # Only lower bound: target_value >= lb
                                if target_value >= (shrinkage_MD_lb - self.FLOAT_TOLERANCE):
                                    matching_shrinkage_md_narts.add(nart)
                                    break

            matching_narts &= matching_shrinkage_md_narts
        
        # Filter by shrinkage CD (适用于 Backing 和 Liner)
        if (shrinkage_CD_lb is not None or shrinkage_CD_ub is not None) and material_type.lower() in ("backing", "liner"):
            shrinkage_cd_records = df[
                df['property_key'].str.contains('shrinkage.*cd', case=False, na=False, regex=True)
            ]

            matching_shrinkage_cd_narts = set()
            for nart in narts:
                nart_records = shrinkage_cd_records[shrinkage_cd_records[nart_col] == nart]
                if len(nart_records) > 0:
                    for _, record in nart_records.iterrows():
                        target_value = record.get('target_value')
                        if pd.notna(target_value):
                            # Apply the same logic as search_products
                            # 使用容差处理浮点数精度问题
                            if shrinkage_CD_lb is not None and shrinkage_CD_ub is not None:
                                # Both bounds: lb <= target_value <= ub
                                if (shrinkage_CD_lb - self.FLOAT_TOLERANCE) <= target_value <= (shrinkage_CD_ub + self.FLOAT_TOLERANCE):
                                    matching_shrinkage_cd_narts.add(nart)
                                    break
                            elif shrinkage_CD_ub is not None:
                                # Only upper bound: target_value <= ub
                                if target_value <= (shrinkage_CD_ub + self.FLOAT_TOLERANCE):
                                    matching_shrinkage_cd_narts.add(nart)
                                    break
                            else:
                                # Only lower bound: target_value >= lb
                                if target_value >= (shrinkage_CD_lb - self.FLOAT_TOLERANCE):
                                    matching_shrinkage_cd_narts.add(nart)
                                    break

            matching_narts &= matching_shrinkage_cd_narts
        
        # Convert to material objects
        material_list = []
        for nart in matching_narts:
            nart_records = df[df[nart_col] == nart]

            # Extract properties
            properties = []
            for _, record in nart_records.iterrows():
                property_key = record.get('property_key', '')
                # Extract property name from property_key
                # Format: "material_type##property_name##unit##test_method##"
                parts = property_key.split('##')
                if len(parts) >= 2:
                    property_name = parts[1]
                else:
                    property_name = property_key

                # Get test method based on material type
                test_method = None
                if material_type.lower() == "liner":
                    # For liner, use 'Test Methods' column
                    test_method_value = record.get('Test Methods')
                    if pd.notna(test_method_value):
                        test_method = str(test_method_value)
                elif material_type.lower() == "backing":
                    # For backing, use 'tesa + DIN/ISO Standard' column
                    test_method_value = record.get('tesa + DIN/ISO Standard')
                    if pd.notna(test_method_value):
                        test_method = str(test_method_value)
                elif material_type.lower() == "adhesive":
                    # For adhesive, extract from property_key (3rd part is condition/test method)
                    if len(parts) >= 3:
                        condition = parts[2]
                        if condition:
                            test_method = condition

                # Only add if has valid target_value or property_value
                if pd.notna(record.get('target_value')) or pd.notna(record.get('property_value')):
                    # 检查该属性是否是搜索条件中使用的核心属性
                    is_search_criteria = False
                    property_key_lower = property_key.lower()
                    for pattern in search_criteria_property_patterns:
                        if pattern in property_key_lower:
                            is_search_criteria = True
                            break

                    prop = Property(
                        name=property_name,
                        description=None,  # Material properties don't have descriptions in the table
                        lb=record.get('lb') if pd.notna(record.get('lb')) else None,
                        ub=record.get('ub') if pd.notna(record.get('ub')) else None,
                        value=str(record.get('property_value')) if pd.notna(record.get('property_value')) else None,
                        test_method=test_method,
                        is_search_criteria=is_search_criteria
                    )
                    properties.append(prop)

            # Create material object
            material = material_class(
                NART=nart,
                properties=properties
            )
            material_list.append(material)

        return material_list

    def search_by_nart(self, nart: str, target_type: str) -> tuple[Optional[Union[Product, Adhesive, Backing, Liner]], str]:
        """
        根据 NART 和目标类型搜索产品或材料

        Args:
            nart: NART 编号
            target_type: 目标类型 ("product", "adhesive", "liner", "backing")

        Returns:
            tuple: (搜索结果, 类型说明)
        """
        # 根据目标类型在对应的表中搜索
        if target_type == "product":
            # 在产品表中搜索
            product_records = self.df_product_extended[
                self.df_product_extended['Product_Spec'].astype(str).str.strip() == str(nart).strip()
            ]

            if product_records.empty:
                return None, "not_found"

            # 取第一条记录
            record = product_records.iloc[0]

            # 收集标签
            labels = []
            if pd.notna(record.get('L1')) and record.get('L1') != '':
                labels.append(str(record.get('L1')))
            if pd.notna(record.get('L2')) and record.get('L2') != '':
                labels.append(str(record.get('L2')))

            # 收集属性
            properties = []
            product_spec = record['Product_Spec']

            # Add all properties that have values
            for col in record.index:
                if col.startswith('P') and col.endswith('_target_value'):
                    item_no = col.replace('_target_value', '')
                    if pd.notna(record[col]):
                        # Query df_product for property_value, test_method, and description
                        # Filter by Product Spec and Item No.
                        product_records = self.df_product[
                            (self.df_product['Product Spec'] == product_spec) &
                            (self.df_product['Item No.'] == item_no)
                        ]

                        property_value = None
                        test_method = None
                        description = None

                        if len(product_records) > 0:
                            # Get the first matching record
                            prod_record = product_records.iloc[0]
                            property_value = prod_record.get('property_value')
                            test_method = prod_record.get('Test Method')
                            # Get description from df_product (Item Description column)
                            description = prod_record.get('Item Description')

                            # Convert to string if not None
                            if pd.notna(property_value):
                                property_value = str(property_value)
                            else:
                                property_value = None

                            if pd.notna(test_method):
                                test_method = str(test_method)
                            else:
                                test_method = None

                            if pd.notna(description):
                                description = str(description)
                            else:
                                description = None

                        # Fallback to item_name_mapping if description not found in df_product
                        if description is None:
                            description = self.item_name_mapping.get(item_no)

                        # NART 搜索不使用搜索条件，所以 is_search_criteria 为 False
                        properties.append(Property(
                            name=item_no,
                            description=description,
                            lb=record.get(f'{item_no}_lb'),
                            ub=record.get(f'{item_no}_ub'),
                            value=property_value,
                            test_method=test_method,
                            is_search_criteria=False
                        ))

            # 构建产品对象
            product = Product(
                NART=record['Product_Spec'],
                product_type='double_liner' if record.get('Product_type') == 1 else 'single_liner',
                Liner_NART=record.get('Liner_NART') if pd.notna(record.get('Liner_NART')) else None,
                In_Liner_NART=record.get('In_Liner_NART') if pd.notna(record.get('In_Liner_NART')) else None,
                Out_Liner_NART=record.get('Out_Liner_NART') if pd.notna(record.get('Out_Liner_NART')) else None,
                Open_Adhesive_NART=record.get('Open_Adhesive_NART') if pd.notna(record.get('Open_Adhesive_NART')) else None,
                Cover_Adhesive_NART=record.get('Cover_Adhesive_NART') if pd.notna(record.get('Cover_Adhesive_NART')) else None,
                Backing_NART=record.get('Backing_NART') if pd.notna(record.get('Backing_NART')) else None,
                labels=labels,
                properties=properties
            )

            return product, "product"

        elif target_type == "adhesive":
            # 在 Adhesive 表中搜索
            adhesive_records = self.df_adhesive[
                self.df_adhesive['Adhesive'].astype(str).str.strip() == str(nart).strip()
            ]

            if adhesive_records.empty:
                return None, "not_found"

            # 收集属性
            properties = []
            for _, record in adhesive_records.iterrows():
                property_key = record.get('property_key', '')
                # Extract property name from property_key
                # Format: "adhesive##property_name##condition##"
                parts = property_key.split('##')
                if len(parts) >= 2:
                    property_name = parts[1]
                else:
                    property_name = property_key

                # Extract test method from property_key (3rd part is condition/test method)
                test_method = None
                if len(parts) >= 3:
                    condition = parts[2]
                    if condition:
                        test_method = condition

                # Only add if has valid target_value or property_value
                if pd.notna(record.get('target_value')) or pd.notna(record.get('property_value')):
                    # NART 搜索不使用搜索条件，所以 is_search_criteria 为 False
                    prop = Property(
                        name=property_name,
                        description=None,
                        lb=record.get('lb') if pd.notna(record.get('lb')) else None,
                        ub=record.get('ub') if pd.notna(record.get('ub')) else None,
                        value=str(record.get('property_value')) if pd.notna(record.get('property_value')) else None,
                        test_method=test_method,
                        is_search_criteria=False
                    )
                    properties.append(prop)

            # 构建 Adhesive 对象
            adhesive = Adhesive(
                NART=nart,
                properties=properties
            )

            return adhesive, "adhesive"

        elif target_type == "liner":
            # 在 Liner 表中搜索
            liner_records = self.df_liner[
                self.df_liner['Liner'].astype(str).str.strip() == str(nart).strip()
            ]

            if liner_records.empty:
                return None, "not_found"

            # 收集属性
            properties = []
            for _, record in liner_records.iterrows():
                property_key = record.get('property_key', '')
                # Extract property name from property_key
                # Format: "liner##property_name##unit##test_method##"
                parts = property_key.split('##')
                if len(parts) >= 2:
                    property_name = parts[1]
                else:
                    property_name = property_key

                # For liner, use 'Test Methods' column
                test_method = None
                test_method_value = record.get('Test Methods')
                if pd.notna(test_method_value):
                    test_method = str(test_method_value)

                # Only add if has valid target_value or property_value
                if pd.notna(record.get('target_value')) or pd.notna(record.get('property_value')):
                    # NART 搜索不使用搜索条件，所以 is_search_criteria 为 False
                    prop = Property(
                        name=property_name,
                        description=None,
                        lb=record.get('lb') if pd.notna(record.get('lb')) else None,
                        ub=record.get('ub') if pd.notna(record.get('ub')) else None,
                        value=str(record.get('property_value')) if pd.notna(record.get('property_value')) else None,
                        test_method=test_method,
                        is_search_criteria=False
                    )
                    properties.append(prop)

            # 构建 Liner 对象
            liner = Liner(
                NART=nart,
                properties=properties
            )

            return liner, "liner"

        elif target_type == "backing":
            # 在 Backing 表中搜索
            backing_records = self.df_backing[
                self.df_backing['Backing'].astype(str).str.strip() == str(nart).strip()
            ]

            if backing_records.empty:
                return None, "not_found"

            # 收集属性
            properties = []
            for _, record in backing_records.iterrows():
                property_key = record.get('property_key', '')
                # Extract property name from property_key
                # Format: "backing##property_name##unit##test_method##"
                parts = property_key.split('##')
                if len(parts) >= 2:
                    property_name = parts[1]
                else:
                    property_name = property_key

                # For backing, use 'tesa + DIN/ISO Standard' column
                test_method = None
                test_method_value = record.get('tesa + DIN/ISO Standard')
                if pd.notna(test_method_value):
                    test_method = str(test_method_value)

                # Only add if has valid target_value or property_value
                if pd.notna(record.get('target_value')) or pd.notna(record.get('property_value')):
                    # NART 搜索不使用搜索条件，所以 is_search_criteria 为 False
                    prop = Property(
                        name=property_name,
                        description=None,
                        lb=record.get('lb') if pd.notna(record.get('lb')) else None,
                        ub=record.get('ub') if pd.notna(record.get('ub')) else None,
                        value=str(record.get('property_value')) if pd.notna(record.get('property_value')) else None,
                        test_method=test_method,
                        is_search_criteria=False
                    )
                    properties.append(prop)

            # 构建 Backing 对象
            backing = Backing(
                NART=nart,
                properties=properties
            )

            return backing, "backing"

        return None, "not_found"
