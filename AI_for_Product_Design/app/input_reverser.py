import json
from enum import StrEnum
from pathlib import Path
from typing import List

import joblib
import numpy as np
import ortools
import pandas as pd
from ortools.linear_solver import pywraplp
from pydantic import BaseModel, Field
from sklearn.preprocessing import StandardScaler

# 产品属性Item No常量
ITEM_NO_COVER_PA = "P4005"
ITEM_NO_OPEN_PA = "P4006"
ITEM_NO_TOTAL_THICKNESS = "P4433"

# 数据文件路径
DATA_FILE_PRODUCT = "data/df_product.csv"
DATA_FILE_PRODUCT_EXTENDED = "data/df_product_extended.csv"
DATA_FILE_ADHESIVE = "data/df_adhesive_properties.csv"
DATA_FILE_LINER = "data/df_liner_properties.csv"
DATA_FILE_BACKING = "data/df_backing_properties.csv"
DATA_FILE_ITEM_NO = "data/item_no_name_mapping.csv"

# 模型文件路径模板
MODEL_FILE_TEMPLATE = "models/lr_model_{}.joblib"
MODEL_INFO_FILE_TEMPLATE = "models/lr_model_{}_info.json"

# DataFrame列名常量
COLUMN_ITEM_NO = "Item_No"
COLUMN_ITEM_NAME = "Item_Name"
COLUMN_PROPERTY_KEY = "property_key"
COLUMN_TARGET_VALUE = "target_value"

# 特征名前缀和完整特征名
FEATURE_COVER_COATING_WEIGHT = "feature##cover_coating_weight"
FEATURE_OPEN_COATING_WEIGHT = "feature##open_coating_weight"
FEATURE_BACKING_THICKNESS = "feature##backing_thickness"
FEATURE_OPEN_ADHESIVE_PA = "feature##open_adhesive_PA"
FEATURE_COVER_ADHESIVE_PA = "feature##cover_adhesive_PA"
FEATURE_TOTAL_THICKNESS = "feature##total_thickness"

# 预测结果列名前缀和完整列名
PREDICTED_PREFIX = "Pre_"
PREDICTED_COVER_PA = "Pred_cover_PA"
PREDICTED_OPEN_PA = "Pred_open_PA"
PREDICTED_TOTAL_THICKNESS = "Pred_total_thickness"

TARGET_COVER_PA = "Target_cover_PA"
TARGET_OPEN_PA = "Target_open_PA"
TARGET_TOTAL_THICKNESS = "Target_total_thickness"
COLUMN_DIFFERENCE_RATIO = "difference_ratio"

# 模型信息字典的键
MODEL_INFO_KEY_MODEL = "model"
MODEL_INFO_KEY_INFO = "info"
MODEL_INFO_KEY_FEATURE_COLUMNS = "feature_columns"
MODEL_INFO_KEY_SCALER = "scaler"


# 求解器配置文件
SOLVER_CONFIG_FILE = "data/solver/feature_weight_by_target.json"

# 文件分隔符
CSV_SEPARATOR = "|"

# 默认值
DEFAULT_FEATURE_VALUE = 0

# 数值常量
DIVISION_FACTOR = 3.0

# 输出分隔线
OUTPUT_SEPARATOR = "-" * 120

# 基础目录路径
BASE_DIR = Path(__file__).parent.parent


class EvalType(StrEnum):
    TOTAL_THICKNESS = "总厚度"
    OPEN_PA = "开放面剥离粘合力"
    COVER_PA = "盖面剥离粘合力"
    OPEN_COATING_WEIGHT = "开放面涂布量"
    COVER_COATING_WEIGHT = "盖面涂布量"


class ProductEvalDetail(BaseModel):
    eval_type: EvalType = Field(
        ..., description="评估类型，如总厚度、开放面剥离粘合力等"
    )

    expect_value: float = Field(..., description="目标值")
    predict_value: float = Field(..., description="预测值")
    score: float = Field(..., description="该属性的匹配分数，范围0~1，1表示完全匹配")
    notes: str = Field(
        ...,
        description="评估备注信息。如果匹配率大于99%， 则设置为'完全满足'，如果小于90%，则设置为'无法满足'。 如果介于两者之间，则设置为'部分满足'",
    )


class ProductPredictedProperty(BaseModel):
    """
    基于材料组合预测的产品属性。
    """

    # 预测材料属性
    predict_backing_thickness: float = Field(
        ..., description="预测的基材厚度，单位：微米(µm)"
    )
    available_backing_NART: List[str] | None = Field(default=None, description="满足预测的backing thickness 的backing NART号")

    predict_open_adhesive_PA: float = Field(
        ..., description="预测的开放面胶粘剂剥离粘合力，单位：牛/厘米(N/cm)"
    )
    available_open_adhesive_NART: List[str] | None = Field(default=None, description="满足预测的open adhesive PA 的open adhesive NART号")

    predict_open_coating_weight: float = Field(
        ..., description="预测的开放面涂布量，单位：克/平方米(g/m²)"
    )

    predict_cover_adhesive_PA: float = Field(
        ..., description="预测的盖面胶粘剂剥离粘合力，单位：牛/厘米(N/cm)"
    )
    available_cover_adhesive_NART: List[str] | None = Field(default=None, description="满足预测的cover adhesive PA 的cover adhesive NART号")

    predict_cover_coating_weight: float = Field(
        ..., description="预测的盖面涂布量，单位：克/平方米(g/m²)"
    )

    eval_details: list[ProductEvalDetail] = Field(
        ..., description="各评估属性的详细信息"
    )

    overall_score: float = Field(
        ...,
        description="整体匹配分数，范围0~1，1表示完全匹配。基于各评估属性的平均分数计算得出",
    )


def solve_material_choice(
    target_open_PA,
    target_cover_PA,
    target_thickness_without_liner,
    weight_thickness_penalty=1,
    weight_open_pa_penalty=1,
    weight_cover_pa_penalty=1,
):
    solver = pywraplp.Solver.CreateSolver("SCIP")
    bigM = 10**10
    smallM = 10 ** (-10)
    infinity = solver.infinity()

    with open(f"{BASE_DIR}/{SOLVER_CONFIG_FILE}", "r") as f:
        coef = json.load(f)

    DV = {
        "open_coating_weight": solver.IntVar(
            0, infinity, f"""open side coating weight"""
        ),
        "cover_coating_weight": solver.IntVar(
            0, infinity, f"""cover side coating weight"""
        ),
    }

    for i in range(len(coef["adhesive_PA_all_values"])):
        DV[f"""cover_uses_PA_{i}"""] = solver.IntVar(
            0, 1, f"""whether choose PA {i} for cover"""
        )

    for i in range(len(coef["adhesive_PA_all_values"])):
        DV[f"""open_uses_PA_{i}"""] = solver.IntVar(
            0, 1, f"""whether choose PA {i} for open"""
        )

    for i in range(len(coef["backing_thickness_all_values"])):
        DV[f"""is_backing_{i}"""] = solver.IntVar(
            0, 1, f"""whether choose backing {i}"""
        )

    # Cover Adhesive PA:
    cover_adhesive_PA = np.sum(
        [
            DV[f"""cover_uses_PA_{i}"""] * coef["adhesive_PA_all_values"][i]
            for i in range(len(coef["adhesive_PA_all_values"]))
        ]
    )
    count_cover_adhesive_PA = np.sum(
        [
            DV[f"""cover_uses_PA_{i}"""]
            for i in range(len(coef["adhesive_PA_all_values"]))
        ]
    )
    # Only one for Cover Side
    solver.Add(count_cover_adhesive_PA == 1)

    # Cover Adhesive PA:
    open_adhesive_PA = np.sum(
        [
            DV[f"""open_uses_PA_{i}"""] * coef["adhesive_PA_all_values"][i]
            for i in range(len(coef["adhesive_PA_all_values"]))
        ]
    )
    count_open_adhesive_PA = np.sum(
        [
            DV[f"""open_uses_PA_{i}"""]
            for i in range(len(coef["adhesive_PA_all_values"]))
        ]
    )
    # Only one for Cover Side
    solver.Add(count_open_adhesive_PA == 1)

    # Backing Thickness:
    backing_thickness = np.sum(
        [
            DV[f"""is_backing_{i}"""] * coef["backing_thickness_all_values"][i]
            for i in range(len(coef["backing_thickness_all_values"]))
        ]
    )
    count_backing = np.sum(
        [
            DV[f"""is_backing_{i}"""]
            for i in range(len(coef["backing_thickness_all_values"]))
        ]
    )
    # Only one for Cover Side
    solver.Add(count_backing == 1)

    # Cover Coating Weight
    cover_coating_weight = 1000 * DV["cover_coating_weight"]

    # Open Coating Weight
    open_coating_weight = 1000 * DV["open_coating_weight"]

    # Target 1: Open PA
    open_PA = (
        coef["open_PA"]["feature##backing_thickness"] * backing_thickness
        + coef["open_PA"]["feature##cover_adhesive_PA"] * cover_adhesive_PA
        + coef["open_PA"]["feature##open_adhesive_PA"] * open_adhesive_PA
        + coef["open_PA"]["feature##cover_coating_weight"] * cover_coating_weight
        + coef["open_PA"]["feature##open_coating_weight"] * open_coating_weight
        + coef["open_PA"]["bias"]
    )

    # Target 2: Cover PA
    cover_PA = (
        coef["cover_PA"]["feature##backing_thickness"] * backing_thickness
        + coef["cover_PA"]["feature##cover_adhesive_PA"] * cover_adhesive_PA
        + coef["cover_PA"]["feature##open_adhesive_PA"] * open_adhesive_PA
        + coef["cover_PA"]["feature##cover_coating_weight"] * cover_coating_weight
        + coef["cover_PA"]["feature##open_coating_weight"] * open_coating_weight
        + coef["cover_PA"]["bias"]
    )

    # Target 3: Thickness without Liner
    thickness_without_liner = (
        coef["total_thickness"]["feature##backing_thickness"] * backing_thickness
        + coef["total_thickness"]["feature##cover_adhesive_PA"] * cover_adhesive_PA
        + coef["total_thickness"]["feature##open_adhesive_PA"] * open_adhesive_PA
        + coef["total_thickness"]["feature##cover_coating_weight"]
        * cover_coating_weight
        + coef["total_thickness"]["feature##open_coating_weight"] * open_coating_weight
        + coef["total_thickness"]["bias"]
    )

    # Thickness Penalty:
    # thickness_penalty = abs(thickness_without_liner - target_thickness_without_liner)
    DV["thickness_penalty"] = solver.NumVar(
        0, infinity, "abs(thickness_without_liner - target_thickness_without_liner)"
    )
    solver.Add(
        DV["thickness_penalty"]
        >= target_thickness_without_liner - thickness_without_liner
    )
    solver.Add(
        DV["thickness_penalty"]
        >= thickness_without_liner - target_thickness_without_liner
    )

    # Open PA Penalty:
    # if open_pa >= open_pa_target, then penalty = 0. else, penalty = open_pa_target - open_pa
    DV["open_pa_penalty"] = solver.NumVar(
        0,
        infinity,
        "if open_pa >= open_pa_target, then penalty = 0. else, penalty = open_pa_target - open_pa",
    )
    solver.Add(DV["open_pa_penalty"] >= target_open_PA - open_PA)

    # Cover PA Penalty:
    # if cover_pa >= cover_pa_target, then penalty = 0. else, penalty = cover_pa_target - cover_pa
    DV["cover_pa_penalty"] = solver.NumVar(
        0,
        infinity,
        "if cover_pa >= cover_pa_target, then penalty = 0. else, penalty = cover_pa_target - cover_pa",
    )
    solver.Add(DV["cover_pa_penalty"] >= target_cover_PA - cover_PA)

    Objective = (
        weight_thickness_penalty * DV["thickness_penalty"]
        + weight_cover_pa_penalty * DV["cover_pa_penalty"]
        + weight_open_pa_penalty * DV["open_pa_penalty"]
    )

    solver.Minimize(Objective)

    status = solver.Solve()

    cover_adhesive_choice_id = -1
    for i in range(len(coef["adhesive_PA_all_values"])):
        if DV[f"""cover_uses_PA_{i}"""].solution_value() > 0.5:
            cover_adhesive_choice_id = i

    open_adhesive_choice_id = -1
    for i in range(len(coef["adhesive_PA_all_values"])):
        if DV[f"""open_uses_PA_{i}"""].solution_value() > 0.5:
            open_adhesive_choice_id = i

    backing_choice_id = -1
    for i in range(len(coef["backing_thickness_all_values"])):
        if DV[f"""is_backing_{i}"""].solution_value() > 0.5:
            backing_choice_id = i

    return {
        "Cover Adhesive Choice ID": cover_adhesive_choice_id,
        "Cover Adhesive Coating Weight": cover_coating_weight.solution_value(),
        "Open Adhesive Choice ID": open_adhesive_choice_id,
        "Open Adhesive Coating Weight": open_coating_weight.solution_value(),
        "Backing Adhesive Choice ID": backing_choice_id,
        "Open PA": open_PA.solution_value(),
        "Cover PA": cover_PA.solution_value(),
        "Thickness without Liner": thickness_without_liner.solution_value(),
    }


class InputReverser:
    """反向推导材料组合的核心类。

    根据用户指定的产品性能需求（剥离粘合力、厚度等），通过机器学习模型预测
    所有可能的特征组合，并返回最优的材料配置方案。

    Attributes:
        df_product (pd.DataFrame): 产品基础信息表
        df_product_extended (pd.DataFrame): 扩展产品信息表，包含详细的产品属性
        df_adhesive (pd.DataFrame): 胶粘剂材料属性表
        df_liner (pd.DataFrame): 离型纸材料属性表
        df_backing (pd.DataFrame): 基材材料属性表
        df_item_no (pd.DataFrame): 产品属性编号与名称映射表
        item_name_mapping (dict): Item_No到Item_Name的快速查找字典
        model_info (dict): 包含所有预测模型及其配置的字典，键为模型名称(P4005/P4006/P4433)
        backing_thickness_key_word (str): backing厚度属性的搜索关键词
        adhesive_peel_adhesion_key_word (str): adhesive剥离粘合力属性的搜索关键词
        feature_space (list): 所有模型特征的并集列表(已排序)
        backing_thickness_values (list): backing厚度的所有可能取值
        adhesive_peel_adhesion_values (list): adhesive剥离粘合力的所有可能取值
        first_coating_weight_values (list): cover side涂布量的所有可能取值
        second_coating_weight_values (list): open side涂布量的所有可能取值
        df_feature_space (pd.DataFrame): 所有特征组合的笛卡尔积
        df_predictions (pd.DataFrame): 包含预测结果和差异比率的DataFrame
    """

    def __init__(self):
        """初始化InputReverser实例。

        加载所有必要的数据表（产品、材料、属性等）和预测模型。
        设置材料属性搜索关键词和Item编号映射字典。
        """
        # 读取依赖的数据表
        self.df_product = pd.read_csv(BASE_DIR / DATA_FILE_PRODUCT, sep=CSV_SEPARATOR)
        self.df_product_extended = pd.read_csv(
            BASE_DIR / DATA_FILE_PRODUCT_EXTENDED, sep=CSV_SEPARATOR
        )
        self.df_adhesive = pd.read_csv(BASE_DIR / DATA_FILE_ADHESIVE, sep=CSV_SEPARATOR)
        self.df_liner = pd.read_csv(BASE_DIR / DATA_FILE_LINER, sep=CSV_SEPARATOR)
        self.df_backing = pd.read_csv(BASE_DIR / DATA_FILE_BACKING, sep=CSV_SEPARATOR)
        self.df_item_no = pd.read_csv(BASE_DIR / DATA_FILE_ITEM_NO, sep=CSV_SEPARATOR)

        # Create a mapping dictionary for quick lookup: Item_No -> Item_Name
        self.item_name_mapping = dict(
            zip(self.df_item_no[COLUMN_ITEM_NO], self.df_item_no[COLUMN_ITEM_NAME])
        )

        # 读取模型和配置信息
        self.model_info = {}
        for model_key in [ITEM_NO_COVER_PA, ITEM_NO_OPEN_PA, ITEM_NO_TOTAL_THICKNESS]:
            model_path = BASE_DIR / MODEL_FILE_TEMPLATE.format(model_key)
            info_path = BASE_DIR / MODEL_INFO_FILE_TEMPLATE.format(model_key)
            model = joblib.load(model_path)
            info = pd.read_json(info_path, typ="series").to_dict()

            scaler = StandardScaler()
            if "scaler_mean" in info and "scaler_scale" in info:
                scaler.mean_ = np.array(info["scaler_mean"])
                scaler.scale_ = np.array(info["scaler_scale"])
            else:
                print(
                    f"Warning: Scaler info not found for model {model_key}. Predictions may be inaccurate."
                )
                scaler.mean_ = np.zeros(
                    len(info.get(MODEL_INFO_KEY_FEATURE_COLUMNS, []))
                )
                scaler.scale_ = np.ones(
                    len(info.get(MODEL_INFO_KEY_FEATURE_COLUMNS, []))
                )

            self.model_info[model_key] = {
                MODEL_INFO_KEY_MODEL: model,
                MODEL_INFO_KEY_INFO: info,
                MODEL_INFO_KEY_SCALER: scaler,
            }

        # 用于property搜索的关键词映射
        self.backing_thickness_key_word = "backing##thickness##"
        self.adhesive_peel_adhesion_key_word = "adhesive##peel adhesion (n/cm)##sus##"

    def build_feature_space(
        self,
        backing_thickness_lb: float | None = None,
        backing_thickness_ub: float | None = None,
        cover_coating_weight_lb: float | None = None,
        cover_coating_weight_ub: float | None = None,
        open_coating_weight_lb: float | None = None,
        open_coating_weight_ub: float | None = None,
    ):
        """构造各个特征的空间。

        从所有模型中提取特征，获取每个特征维度的所有可能取值。

        Args:
            backing_thickness_lb: backing thickness的下限
            backing_thickness_ub: backing thickness的上限
            cover_coating_weight_lb: cover side coating weight的下界
            cover_coating_weight_ub: cover side coating weight的上界
            open_coating_weight_lb: open side coating weight的下界
            open_coating_weight_ub: open side coating weight的上界

        Returns:
            None. 设置实例变量：
            - feature_space: 所有模型特征的并集列表
            - backing_thickness_values: backing厚度的所有唯一值
            - adhesive_PA_values: adhesive剥离粘合力的所有唯一值
            - cover_coating_weight_values: cover side涂布量的所有唯一值
            - open_coating_weight_values: open side涂布量的所有唯一值
        """
        # 取各个模型的特征并集作为feature space
        feature_keys = set()
        for model_key, model_data in self.model_info.items():
            info = model_data[MODEL_INFO_KEY_INFO]
            feature_list = info.get(MODEL_INFO_KEY_FEATURE_COLUMNS, [])
            feature_keys.update(feature_list)
        self.feature_space = sorted(feature_keys)
        print("Feature Space Keys:", self.feature_space)

        # 处理backing_thickness的上下界
        if backing_thickness_lb is not None and backing_thickness_ub is not None:
            # 如果lb和ub都有值，则均匀采样10个点
            backing_thickness_values = np.linspace(
                backing_thickness_lb, backing_thickness_ub, 10
            ).tolist()
        elif backing_thickness_lb is None and backing_thickness_ub is None:
            # 如果lb和ub都为空，则使用df_backing中的thickness值
            df_backing_thickness = self.df_backing[
                self.df_backing[COLUMN_PROPERTY_KEY].str.contains(
                    self.backing_thickness_key_word, regex=False
                )
            ][COLUMN_TARGET_VALUE].copy()
            # 确保转换为数值类型
            df_backing_thickness = pd.to_numeric(df_backing_thickness, errors='coerce')
            backing_thickness_values = (
                df_backing_thickness[df_backing_thickness.notna()]
                .unique()
                .tolist()
            )
        elif backing_thickness_lb is None and backing_thickness_ub is not None:
            # 如果lb为空而ub非空，使用df_backing中thickness的最小值作为lb
            df_backing_thickness = self.df_backing[
                self.df_backing[COLUMN_PROPERTY_KEY].str.contains(
                    self.backing_thickness_key_word, regex=False
                )
            ][COLUMN_TARGET_VALUE]
            # 确保转换为数值类型
            df_backing_thickness = pd.to_numeric(df_backing_thickness, errors='coerce')
            min_thickness = df_backing_thickness.min()
            backing_thickness_values = np.linspace(
                min_thickness, backing_thickness_ub, 10
            ).tolist()
        else:  # backing_thickness_lb is not None and backing_thickness_ub is None
            # 如果lb非空而ub为空，使用df_backing中thickness的最大值作为ub
            df_backing_thickness = self.df_backing[
                self.df_backing[COLUMN_PROPERTY_KEY].str.contains(
                    self.backing_thickness_key_word, regex=False
                )
            ][COLUMN_TARGET_VALUE]
            # 确保转换为数值类型
            df_backing_thickness = pd.to_numeric(df_backing_thickness, errors='coerce')
            max_thickness = df_backing_thickness.max()
            backing_thickness_values = np.linspace(
                backing_thickness_lb, max_thickness, 10
            ).tolist()

        backing_thickness_values.sort()
        self.backing_thickness_values = backing_thickness_values
        print(
            f"backing_thickness_values num: {len(backing_thickness_values)}:\n",
            backing_thickness_values,
            "\n",
            OUTPUT_SEPARATOR,
        )

        # 根据adhesive peel adhesion key word 获取adhesive peel adhesion的所有可能值
        df_adhesive_pa = self.df_adhesive[
            self.df_adhesive[COLUMN_PROPERTY_KEY].str.contains(
                self.adhesive_peel_adhesion_key_word, regex=False
            )
        ].copy()
        
        # 将target_value转换为数值类型，无效值转为NaN
        df_adhesive_pa[COLUMN_TARGET_VALUE] = pd.to_numeric(
            df_adhesive_pa[COLUMN_TARGET_VALUE], errors='coerce'
        )
        
        # 过滤掉NaN值并获取唯一值
        adhesive_PA_values = (
            df_adhesive_pa[df_adhesive_pa[COLUMN_TARGET_VALUE].notna()][COLUMN_TARGET_VALUE]
            .unique()
            .tolist()
        )
        adhesive_PA_values.sort()
        self.adhesive_PA_values = adhesive_PA_values
        print(
            f"adhesive_peel_adhesion_values num: {len(adhesive_PA_values)}:\n",
            adhesive_PA_values,
            "\n",
            OUTPUT_SEPARATOR,
        )

        # 首先生成coating weight的采样值
        # 处理cover_coating_weight的上下界
        # 将 cover_coating_weight_lb 和 cover_coating_weight_ub 取整到1000的整倍数上
        if cover_coating_weight_lb is not None:
            cover_coating_weight_lb = int(
                np.floor(cover_coating_weight_lb / 1000) * 1000
            )
        if cover_coating_weight_ub is not None:
            cover_coating_weight_ub = int(
                np.ceil(cover_coating_weight_ub / 1000) * 1000
            )
        if cover_coating_weight_lb is not None and cover_coating_weight_ub is not None:
            # 如果lb和ub都有值，则按步长1000采样
            cover_coating_weight_values = np.arange(
                cover_coating_weight_lb, cover_coating_weight_ub + 1, 1000
            ).tolist()
        elif cover_coating_weight_lb is None and cover_coating_weight_ub is None:
            # 如果lb和ub都为空，则使用1000到60000，按步长1000采样
            cover_coating_weight_values = np.arange(1000, 60001, 1000).tolist()
        elif cover_coating_weight_lb is None and cover_coating_weight_ub is not None:
            # 如果lb为空而ub非空，使用1000作为lb，按步长1000采样
            cover_coating_weight_values = np.arange(
                1000, cover_coating_weight_ub + 1, 1000
            ).tolist()
        else:  # cover_coating_weight_lb is not None and cover_coating_weight_ub is None
            # 如果lb非空而ub为空，使用60000作为ub，按步长1000采样
            cover_coating_weight_values = np.arange(
                cover_coating_weight_lb, 60001, 1000
            ).tolist()

        self.cover_coating_weight_values = cover_coating_weight_values
        print(
            f"cover_coating_weight_values num: {len(cover_coating_weight_values)}:\n",
            cover_coating_weight_values,
            "\n",
            OUTPUT_SEPARATOR,
        )

        # 处理open_coating_weight的上下界
        # 将 open_coating_weight_lb 和 open_coating_weight_ub 取整到1000的整倍数上
        if open_coating_weight_lb is not None:
            open_coating_weight_lb = int(np.floor(open_coating_weight_lb / 1000) * 1000)
        if open_coating_weight_ub is not None:
            open_coating_weight_ub = int(np.ceil(open_coating_weight_ub / 1000) * 1000)
        if open_coating_weight_lb is not None and open_coating_weight_ub is not None:
            # 如果lb和ub都有值，则按步长1000采样
            open_coating_weight_values = np.arange(
                open_coating_weight_lb, open_coating_weight_ub + 1, 1000
            ).tolist()
        elif open_coating_weight_lb is None and open_coating_weight_ub is None:
            # 如果lb和ub都为空，则使用1000到60000，按步长1000采样
            open_coating_weight_values = np.arange(1000, 60001, 1000).tolist()
        elif open_coating_weight_lb is None and open_coating_weight_ub is not None:
            # 如果lb为空而ub非空，使用1000作为lb，按步长1000采样
            open_coating_weight_values = np.arange(
                1000, open_coating_weight_ub + 1, 1000
            ).tolist()
        else:  # open_coating_weight_lb is not None and open_coating_weight_ub is None
            # 如果lb非空而ub为空，使用60000作为ub，按步长1000采样
            open_coating_weight_values = np.arange(
                open_coating_weight_lb, 60001, 1000
            ).tolist()

        self.open_coating_weight_values = open_coating_weight_values
        print(
            f"open_coating_weight_values num: {len(open_coating_weight_values)}:\n",
            open_coating_weight_values,
            "\n",
            OUTPUT_SEPARATOR,
        )

    def build_feature_df(self):
        """根据各个特征空间的可能值，构建最终的DataFrame。

        使用笛卡尔积生成所有可能的特征组合。

        Returns:
            None. 设置实例变量：
            - df_feature_space: 包含所有特征组合的DataFrame

        Notes:
            必须先调用build_feature_space()生成各个特征的可能取值。
        """
        # 构建特征值字典
        # 注意：使用模型实际期望的特征名
        feature_value_dict = {
            FEATURE_COVER_COATING_WEIGHT: self.cover_coating_weight_values,
            FEATURE_OPEN_COATING_WEIGHT: self.open_coating_weight_values,
            FEATURE_BACKING_THICKNESS: self.backing_thickness_values,
            FEATURE_OPEN_ADHESIVE_PA: self.adhesive_PA_values,
            FEATURE_COVER_ADHESIVE_PA: self.adhesive_PA_values,
        }

        # 使用itertools生成所有特征组合的笛卡尔积
        from itertools import product as cartesian_product

        # 确保按照feature_space的顺序获取特征值me
        feature_combinations = []
        for feature_name in self.feature_space:
            if feature_name in feature_value_dict:
                feature_combinations.append(feature_value_dict[feature_name])
            else:
                print(
                    f"Warning: feature {feature_name} not found in feature_value_dict"
                )
                feature_combinations.append([DEFAULT_FEATURE_VALUE])  # 默认值

        # 生成所有组合
        all_combinations = list(cartesian_product(*feature_combinations))

        # 转换为DataFrame
        self.df_feature_space = pd.DataFrame(
            all_combinations, columns=self.feature_space
        )

        # 删除total thickness特征列（如果存在），这个列将有模型预测得到
        if FEATURE_TOTAL_THICKNESS in self.df_feature_space.columns:
            self.df_feature_space = self.df_feature_space.drop(
                columns=[FEATURE_TOTAL_THICKNESS]
            )

        print(
            f"Feature space shape: {self.df_feature_space.shape}",
            "\n",
            OUTPUT_SEPARATOR,
        )
        print(
            "Feature space head:",
            "\n",
            self.df_feature_space.head().to_string(),
            "\n",
            OUTPUT_SEPARATOR,
        )

    def predict_target_value(self):
        """使用加载的模型对特征空间中的所有组合进行预测。

        所有三个目标（P4005、P4006、P4433）独立预测，互不依赖。

        Returns:
            None. 设置实例变量df_predictions，包含：
            - 原始特征列
            - predicted_P4433: P4433属性的预测值（总厚度）
            - predicted_P4005: P4005属性的预测值（open side剥离粘合力）
            - predicted_P4006: P4006属性的预测值（cover side剥离粘合力）

        Notes:
            必须先调用build_feature_space()生成特征空间。
        """
        # 复制feature space作为预测结果的基础
        df_predictions = self.df_feature_space.copy()

        # 对所有模型进行独立预测
        for model_key in [ITEM_NO_COVER_PA, ITEM_NO_OPEN_PA, ITEM_NO_TOTAL_THICKNESS]:
            if model_key not in self.model_info:
                continue

            model_data = self.model_info[model_key]
            model = model_data[MODEL_INFO_KEY_MODEL]
            info = model_data[MODEL_INFO_KEY_INFO]
            scaler = model_data[MODEL_INFO_KEY_SCALER]
            feature_columns = info.get(MODEL_INFO_KEY_FEATURE_COLUMNS, [])

            # 确保所有需要的特征列都存在
            missing_features = set(feature_columns) - set(df_predictions.columns)
            if missing_features:
                print(
                    f"Warning: Model {model_key} requires features not in feature space: {missing_features}"
                )
                continue

            # 提取模型需要的特征（按照正确的顺序）
            X = df_predictions[feature_columns]

            # 进行预测
            X_scaled = scaler.transform(X)
            predictions = model.predict(X_scaled)

            # 将预测结果添加到DataFrame
            if model_key == ITEM_NO_COVER_PA:
                df_predictions[PREDICTED_COVER_PA] = predictions
            elif model_key == ITEM_NO_OPEN_PA:
                df_predictions[PREDICTED_OPEN_PA] = predictions
            elif model_key == ITEM_NO_TOTAL_THICKNESS:
                df_predictions[PREDICTED_TOTAL_THICKNESS] = predictions

            print(
                f"Model {model_key} predictions completed. Shape: {predictions.shape}",
                "\n",
                OUTPUT_SEPARATOR,
            )

        # 保存预测结果
        self.df_predictions = df_predictions

        print(
            "All predictions completed.",
            "\n",
            f"Predictions DataFrame shape: {self.df_predictions.shape}",
            "\n",
            OUTPUT_SEPARATOR,
        )
        print(
            "Predictions DataFrame head:",
            "\n",
            self.df_predictions.head().to_string(index=False),
            "\n",
            OUTPUT_SEPARATOR,
        )

    def _calculate_difference_ratio(
        self,
        predict_product_cover_PA: float,
        predicted_product_open_PA: float,
        predicted_product_thickness: float,
        product_cover_PA: float,
        product_open_PA: float,
        product_thickness: float,
    ) -> float:
        """计算预测值与目标值之间的差异比率。

        Args:
            predict_product_cover_PA: 预测的cover side剥离粘合力（P4005）
            predicted_product_open_PA: 预测的open side剥离粘合力（P4006）
            predicted_product_thickness: 预测的总厚度，不含liner（P4433）
            product_cover_PA: 目标cover side剥离粘合力
            product_open_PA: 目标open side剥离粘合力
            product_thickness: 目标总厚度，不含liner

        Returns:
            平均差异比率。如果预测厚度小于目标厚度（违反硬性限制），返回NaN。

        Notes:
            - 差异比率计算公式：|predicted - target| / target
            - 硬性限制：predicted_product_thickness >= product_thickness
            - 返回值为三个属性差异比率的平均值
        """
        # 硬性限制检查：预测的total thickness必须 非负
        if (predicted_product_thickness < product_thickness or predicted_product_thickness < 0):
            return np.nan

        # 计算各个属性的difference ratio
        diff_ratio_product_cover_PA = (
            abs(predict_product_cover_PA - product_cover_PA) / product_cover_PA
        )
        diff_ratio_product_open_PA = (
            abs(predicted_product_open_PA - product_open_PA) / product_open_PA
        )
        diff_ratio_product_thickness = (
            abs(predicted_product_thickness - product_thickness) / product_thickness
        )

        # 返回平均差异比率
        return (
            diff_ratio_product_cover_PA
            + diff_ratio_product_open_PA
            + diff_ratio_product_thickness
        ) / DIVISION_FACTOR

    def _find_backing_nart(
        self, target_thickness: float, tolerance: float = 0.5
    ) -> List[str]:
        """根据目标厚度查找满足条件的backing NART号。

        Args:
            target_thickness: 目标backing厚度值
            tolerance: 匹配的容差，默认0.5微米

        Returns:
            所有匹配的NART号列表，如果没有匹配项返回空列表
        """
        # 筛选backing thickness相关的记录
        df_backing_thickness = self.df_backing[
            self.df_backing[COLUMN_PROPERTY_KEY].str.contains(
                self.backing_thickness_key_word, regex=False
            )
        ].copy()
        
        # 确保target_value是数值类型
        df_backing_thickness[COLUMN_TARGET_VALUE] = pd.to_numeric(
            df_backing_thickness[COLUMN_TARGET_VALUE], errors='coerce'
        )
        
        # 过滤掉NaN值
        df_backing_thickness = df_backing_thickness[
            df_backing_thickness[COLUMN_TARGET_VALUE].notna()
        ]

        # 查找满足条件的记录（在容差范围内）
        matched = df_backing_thickness[
            np.abs(df_backing_thickness[COLUMN_TARGET_VALUE] - target_thickness)
            <= tolerance
        ]

        if not matched.empty:
            # 返回所有匹配的NART号（去重）
            return matched["NART"].unique().tolist()
        return []

    def _find_adhesive_nart(
        self, target_pa: float, tolerance: float = 0.1
    ) -> List[str]:
        """根据目标剥离粘合力查找满足条件的adhesive NART号。

        Args:
            target_pa: 目标adhesive剥离粘合力值
            tolerance: 匹配的容差，默认0.1 N/cm

        Returns:
            所有匹配的NART号列表，如果没有匹配项返回空列表
        """
        # 筛选adhesive peel adhesion相关的记录
        df_adhesive_pa = self.df_adhesive[
            self.df_adhesive[COLUMN_PROPERTY_KEY].str.contains(
                self.adhesive_peel_adhesion_key_word, regex=False
            )
        ].copy()
        
        # 确保target_value是数值类型
        df_adhesive_pa[COLUMN_TARGET_VALUE] = pd.to_numeric(
            df_adhesive_pa[COLUMN_TARGET_VALUE], errors='coerce'
        )
        
        # 过滤掉NaN值
        df_adhesive_pa = df_adhesive_pa[
            df_adhesive_pa[COLUMN_TARGET_VALUE].notna()
        ]

        # 查找满足条件的记录（在容差范围内）
        matched = df_adhesive_pa[
            np.abs(df_adhesive_pa[COLUMN_TARGET_VALUE] - target_pa) <= tolerance
        ]

        if not matched.empty:
            # 返回所有匹配的NART号（去重）
            return matched["NART"].unique().tolist()
        return []

    def search_feature_comb(
        self,
        product_open_side_PA: float,
        product_cover_side_PA: float,
        product_total_thickness: float,
        n_best: int = 5,
        backing_thickness_lb: float | None = None,
        backing_thickness_ub: float | None = None,
        cover_coating_weight_lb: float | None = None,
        cover_coating_weight_ub: float | None = None,
        open_coating_weight_lb: float | None = None,
        open_coating_weight_ub: float | None = None,
    ) -> list[ProductPredictedProperty]:
        """搜索满足目标属性的最佳材料组合。

        构建特征空间，使用模型预测所有组合的属性值，
        计算预测值与目标值的差异比率，返回差异最小的前n个组合。

        Args:
            product_open_side_PA: 目标open side剥离粘合力，单位N/cm
            product_cover_side_PA: 目标cover side剥离粘合力，单位N/cm
            product_total_thickness: 目标总厚度（不含liner），单位µm
            n_best: 返回最佳的前n个特征组合
            backing_thickness_lb: backing thickness的下限
            backing_thickness_ub: backing thickness的上限
            cover_coating_weight_lb: cover side coating weight的下界
            cover_coating_weight_ub: cover side coating weight的上界
            open_coating_weight_lb: open side coating weight的下界
            open_coating_weight_ub: open side coating weight的上界

        Returns:
            包含前n_best个最佳特征组合的ProductPredictedProperty对象列表，按相似度分数降序排序。
        """
        import time

        start_time = time.time()
        # build feature space
        self.build_feature_space(
            backing_thickness_lb=backing_thickness_lb,
            backing_thickness_ub=backing_thickness_ub,
            cover_coating_weight_lb=cover_coating_weight_lb,
            cover_coating_weight_ub=cover_coating_weight_ub,
            open_coating_weight_lb=open_coating_weight_lb,
            open_coating_weight_ub=open_coating_weight_ub,
        )
        # build feature dataframe
        self.build_feature_df()
        # 使用加载的模型，以及df_feature_space, 为每个可能的特征组合预测值
        self.predict_target_value()

        # 添加目标值到df_predictions
        self.df_predictions[TARGET_TOTAL_THICKNESS] = product_total_thickness
        self.df_predictions[TARGET_COVER_PA] = product_cover_side_PA
        self.df_predictions[TARGET_OPEN_PA] = product_open_side_PA

        print(
            "Target values added to predictions DataFrame.",
            "\n",
            f"  target_P4006 (cover side PA): {product_cover_side_PA} N/cm",
            "\n",
            f"  target_P4005 (open side PA): {product_open_side_PA} N/cm",
            "\n",
            f"  target_P4433 (total thickness): {product_total_thickness} µm",
            "\n",
            OUTPUT_SEPARATOR,
        )

        # 使用比对函数计算difference ratio
        self.df_predictions[COLUMN_DIFFERENCE_RATIO] = self.df_predictions.apply(
            lambda row: self._calculate_difference_ratio(
                predict_product_cover_PA=row[PREDICTED_COVER_PA],
                predicted_product_open_PA=row[PREDICTED_OPEN_PA],
                predicted_product_thickness=row[PREDICTED_TOTAL_THICKNESS],
                product_cover_PA=row[TARGET_COVER_PA],
                product_open_PA=row[TARGET_OPEN_PA],
                product_thickness=row[TARGET_TOTAL_THICKNESS],
            ),
            axis=1,
        )

        # 统计满足硬性限制的组合数量
        valid_combinations = self.df_predictions[COLUMN_DIFFERENCE_RATIO].notna().sum()
        total_combinations = len(self.df_predictions)

        print(
            "Difference ratios calculated with hard constraint.",
            "\n",
            "  Hard constraint: predicted_P4433 >= target_P4433",
            "\n",
            f"  Valid combinations: {valid_combinations} / {total_combinations}",
            "\n",
            f"  Mean difference ratio (valid only): {self.df_predictions[COLUMN_DIFFERENCE_RATIO].mean():.4f}",
            "\n",
            f"  Min difference ratio: {self.df_predictions[COLUMN_DIFFERENCE_RATIO].min():.4f}",
            "\n",
            f"  Max difference ratio: {self.df_predictions[COLUMN_DIFFERENCE_RATIO].max():.4f}",
            "\n",
            OUTPUT_SEPARATOR,
        )

        # 按照difference ratio升序排序（最小的最好），NaN值会被排到最后
        df_sorted = self.df_predictions.sort_values(
            by=COLUMN_DIFFERENCE_RATIO, ascending=True
        )

        # 返回前n_best个最佳组合（排除NaN）
        df_best = (
            df_sorted[df_sorted[COLUMN_DIFFERENCE_RATIO].notna()].head(n_best).copy()
        )

        # 转换为ProductPredictedProperty对象列表
        result_list = []
        for _, row in df_best.iterrows():
            # 为每个评估属性创建ProductEvalDetail对象
            eval_details = []

            # 1. 总厚度评估
            thickness_diff_ratio = (
                abs(row[PREDICTED_TOTAL_THICKNESS] - row[TARGET_TOTAL_THICKNESS])
                / row[TARGET_TOTAL_THICKNESS]
            )
            thickness_score = 1.0 / (1.0 + thickness_diff_ratio)
            thickness_match_percent = (1.0 - thickness_diff_ratio) * 100
            if thickness_match_percent >= 90:
                thickness_notes = "完全满足"
            elif thickness_match_percent < 70:
                thickness_notes = "无法满足"
            else:
                thickness_notes = "部分满足"

            eval_details.append(
                ProductEvalDetail(
                    eval_type=EvalType.TOTAL_THICKNESS,
                    expect_value=row[TARGET_TOTAL_THICKNESS],
                    predict_value=row[PREDICTED_TOTAL_THICKNESS],
                    score=thickness_score,
                    notes=thickness_notes,
                )
            )

            # 2. 盖面剥离粘合力评估
            cover_pa_diff_ratio = (
                abs(row[PREDICTED_COVER_PA] - row[TARGET_COVER_PA])
                / row[TARGET_COVER_PA]
            )
            cover_pa_score = 1.0 / (1.0 + cover_pa_diff_ratio)
            cover_pa_match_percent = (1.0 - cover_pa_diff_ratio) * 100
            if cover_pa_match_percent >= 90:
                cover_pa_notes = "完全满足"
            elif cover_pa_match_percent < 70:
                cover_pa_notes = "无法满足"
            else:
                cover_pa_notes = "部分满足"

            eval_details.append(
                ProductEvalDetail(
                    eval_type=EvalType.COVER_PA,
                    expect_value=row[TARGET_COVER_PA],
                    predict_value=row[PREDICTED_COVER_PA],
                    score=cover_pa_score,
                    notes=cover_pa_notes,
                )
            )

            # 3. 开放面剥离粘合力评估
            open_pa_diff_ratio = (
                abs(row[PREDICTED_OPEN_PA] - row[TARGET_OPEN_PA]) / row[TARGET_OPEN_PA]
            )
            open_pa_score = 1.0 / (1.0 + open_pa_diff_ratio)
            open_pa_match_percent = (1.0 - open_pa_diff_ratio) * 100
            if open_pa_match_percent >= 90:
                open_pa_notes = "完全满足"
            elif open_pa_match_percent < 70:
                open_pa_notes = "无法满足"
            else:
                open_pa_notes = "部分满足"

            eval_details.append(
                ProductEvalDetail(
                    eval_type=EvalType.OPEN_PA,
                    expect_value=row[TARGET_OPEN_PA],
                    predict_value=row[PREDICTED_OPEN_PA],
                    score=open_pa_score,
                    notes=open_pa_notes,
                )
            )

            # 计算整体匹配分数（所有评估属性的平均分数）
            overall_score = sum(detail.score for detail in eval_details) / len(
                eval_details
            )

            # 创建ProductPredictedProperty对象
            product_property = ProductPredictedProperty(
                predict_backing_thickness=row[FEATURE_BACKING_THICKNESS],
                predict_open_adhesive_PA=row[FEATURE_OPEN_ADHESIVE_PA],
                predict_open_coating_weight=row[FEATURE_OPEN_COATING_WEIGHT],
                predict_cover_adhesive_PA=row[FEATURE_COVER_ADHESIVE_PA],
                predict_cover_coating_weight=row[FEATURE_COVER_COATING_WEIGHT],
                eval_details=eval_details,
                overall_score=overall_score,
            )
            result_list.append(product_property)

        end_time = time.time()
        elapsed_time = end_time - start_time

        print(
            f"search_feature_comb completed in {elapsed_time:.4f} seconds.",
            "\n",
            f"Top {n_best} best feature combinations found.",
            "\n",
            OUTPUT_SEPARATOR,
        )

        # 为每个结果查找满足预测属性值的NART号
        for product_property in result_list:
            # 查找满足backing thickness的NART号
            product_property.available_backing_NART = self._find_backing_nart(
                product_property.predict_backing_thickness
            )
            
            # 查找满足open adhesive PA的NART号
            product_property.available_open_adhesive_NART = self._find_adhesive_nart(
                product_property.predict_open_adhesive_PA
            )
            
            # 查找满足cover adhesive PA的NART号
            product_property.available_cover_adhesive_NART = self._find_adhesive_nart(
                product_property.predict_cover_adhesive_PA
            )

        return result_list

    def search_by_property(
        self,
        cover_coating_weight: float,
        open_coating_weight: float,
        cover_adhesive_PA: float,
        open_adhesive_PA: float,
        tolerance: float = 1e-6,
    ):
        """根据产品属性在df_product_extended中搜索匹配的产品。

        Args:
            cover_coating_weight: cover side涂布量
            open_coating_weight: open side涂布量
            cover_adhesive_PA: cover side胶粘剂的剥离粘合力
            open_adhesive_PA: open side胶粘剂的剥离粘合力
            tolerance: 数值比对的容差，默认1e-6

        Returns:
            包含匹配产品信息的DataFrame，列包括：
            - Product_Spec: 产品规格
            - cover_coating_weight: cover side涂布量
            - open_coating_weight: open side涂布量
            - cover_adhesive_PA: cover side胶粘剂的剥离粘合力
            - open_adhesive_PA: open side胶粘剂的剥离粘合力
            - cover_PA: cover side剥离粘合力（产品属性P4005）
            - open_PA: open side剥离粘合力（产品属性P4006）
            - Backing_thickness: Backing材料厚度
            - Backing_NART: Backing材料的NART编号
            - Open_Adhesive_NART: Open side胶粘剂的NART编号
            - Cover_Adhesive_NART: Cover side胶粘剂的NART编号

            如果没有找到匹配的产品，返回空的DataFrame。
        """
        # 筛选匹配的产品，使用容差处理浮点数精度问题
        mask = (
            (
                np.abs(
                    self.df_product_extended["cover_coating_weight"]
                    - cover_coating_weight
                )
                <= tolerance
            )
            & (
                np.abs(
                    self.df_product_extended["open_coating_weight"]
                    - open_coating_weight
                )
                <= tolerance
            )
            & (
                np.abs(
                    self.df_product_extended["cover_adhesive_PA"] - cover_adhesive_PA
                )
                <= tolerance
            )
            & (
                np.abs(self.df_product_extended["open_adhesive_PA"] - open_adhesive_PA)
                <= tolerance
            )
        )

        # 获取匹配的产品
        df_matched = self.df_product_extended[mask].copy()

        # 如果没有匹配的产品，返回空DataFrame
        if df_matched.empty:
            print(
                "No matching products found.",
                "\n",
                f"  cover_coating_weight: {cover_coating_weight}",
                "\n",
                f"  open_coating_weight: {open_coating_weight}",
                "\n",
                f"  cover_adhesive_PA: {cover_adhesive_PA}",
                "\n",
                f"  open_adhesive_PA: {open_adhesive_PA}",
                "\n",
                OUTPUT_SEPARATOR,
            )
            return pd.DataFrame(
                columns=[
                    "Product_Spec",
                    "cover_coating_weight",
                    "open_coating_weight",
                    "cover_adhesive_PA",
                    "open_adhesive_PA",
                    "cover_PA",
                    "open_PA",
                    "Backing_thickness",
                    "Backing_NART",
                    "Open_Adhesive_NART",
                    "Cover_Adhesive_NART",
                ]
            )

        # 选择需要返回的列
        # 注意：cover_PA对应P4005_target_value, open_PA对应P4006_target_value
        result_columns = [
            "Product_Spec",
            "cover_coating_weight",
            "open_coating_weight",
            "cover_adhesive_PA",
            "open_adhesive_PA",
        ]

        # 检查cover_PA和open_PA列是否存在，如果存在则添加
        if "cover_PA" in df_matched.columns:
            result_columns.append("cover_PA")
        if "open_PA" in df_matched.columns:
            result_columns.append("open_PA")

        # 添加Backing_thickness列
        if "Backing_thickness" in df_matched.columns:
            result_columns.append("Backing_thickness")

        # 添加NART列
        if "Backing_NART" in df_matched.columns:
            result_columns.append("Backing_NART")
        if "Open_Adhesive_NART" in df_matched.columns:
            result_columns.append("Open_Adhesive_NART")
        if "Cover_Adhesive_NART" in df_matched.columns:
            result_columns.append("Cover_Adhesive_NART")

        df_result = df_matched[result_columns]

        print(
            f"Found {len(df_result)} matching product(s).",
            "\n",
            OUTPUT_SEPARATOR,
        )
        print(
            "Matched products:",
            "\n",
            df_result.to_string(index=False),
            "\n",
            OUTPUT_SEPARATOR,
        )

        return df_result

    def solver(
        self,
        target_open_side_PA: float,
        target_cover_side_PA: float,
        target_total_thickness: float,
    ) -> ProductPredictedProperty:
        with open(f"{BASE_DIR}/{SOLVER_CONFIG_FILE}", "r") as f:
            coef = json.load(f)

        solution = solve_material_choice(
            target_open_PA=target_open_side_PA,
            target_cover_PA=target_cover_side_PA,
            target_thickness_without_liner=target_total_thickness,
        )
        print("solutions:\n", json.dumps(solution, indent=4, ensure_ascii=False))

        predict_open_adhesive_PA = coef["adhesive_PA_all_values"][
            solution["Open Adhesive Choice ID"]
        ]
        predict_cover_adhesive_PA = coef["adhesive_PA_all_values"][
            solution["Cover Adhesive Choice ID"]
        ]
        predict_backing_thickness = coef["backing_thickness_all_values"][
            solution["Backing Adhesive Choice ID"]
        ]
        predict_open_coating_weight = solution["Open Adhesive Coating Weight"]
        predict_cover_coating_weight = solution["Cover Adhesive Coating Weight"]

        predict_cover_PA = solution["Cover PA"]
        predict_open_PA = solution["Open PA"]
        predict_thickness_without_liner = solution["Thickness without Liner"]

        # 拼接 ProductPredictedProperty
        eval_details = []

        # 1. 总厚度评估
        thickness_diff_ratio = (
            abs(predict_thickness_without_liner - target_total_thickness)
            / target_total_thickness
        )
        thickness_score = 1.0 / (1.0 + thickness_diff_ratio)
        thickness_match_percent = (1.0 - thickness_diff_ratio) * 100
        if thickness_match_percent >= 90:
            thickness_notes = "完全满足"
        elif thickness_match_percent < 70:
            thickness_notes = "无法满足"
        else:
            thickness_notes = "部分满足"

        eval_details.append(
            ProductEvalDetail(
                eval_type=EvalType.TOTAL_THICKNESS,
                expect_value=target_total_thickness,
                predict_value=predict_thickness_without_liner,
                score=thickness_score,
                notes=thickness_notes,
            )
        )

        # 2. 盖面剥离粘合力评估
        cover_pa_diff_ratio = (
            abs(predict_cover_PA - target_cover_side_PA) / target_cover_side_PA
        )
        cover_pa_score = 1.0 / (1.0 + cover_pa_diff_ratio)
        cover_pa_match_percent = (1.0 - cover_pa_diff_ratio) * 100
        if cover_pa_match_percent >= 90:
            cover_pa_notes = "完全满足"
        elif cover_pa_match_percent < 70:
            cover_pa_notes = "无法满足"
        else:
            cover_pa_notes = "部分满足"

        eval_details.append(
            ProductEvalDetail(
                eval_type=EvalType.COVER_PA,
                expect_value=target_cover_side_PA,
                predict_value=predict_cover_PA,
                score=cover_pa_score,
                notes=cover_pa_notes,
            )
        )

        # 3. 开放面剥离粘合力评估
        open_pa_diff_ratio = (
            abs(predict_open_PA - target_open_side_PA) / target_open_side_PA
        )
        open_pa_score = 1.0 / (1.0 + open_pa_diff_ratio)
        open_pa_match_percent = (1.0 - open_pa_diff_ratio) * 100
        if open_pa_match_percent >= 90:
            open_pa_notes = "完全满足"
        elif open_pa_match_percent < 70:
            open_pa_notes = "无法满足"
        else:
            open_pa_notes = "部分满足"

        eval_details.append(
            ProductEvalDetail(
                eval_type=EvalType.OPEN_PA,
                expect_value=target_open_side_PA,
                predict_value=predict_open_PA,
                score=open_pa_score,
                notes=open_pa_notes,
            )
        )

        # 计算整体匹配分数
        overall_score = sum(detail.score for detail in eval_details) / len(eval_details)

        # 创建并返回 ProductPredictedProperty 对象
        product_property = ProductPredictedProperty(
            predict_backing_thickness=predict_backing_thickness,
            predict_open_adhesive_PA=predict_open_adhesive_PA,
            predict_open_coating_weight=predict_open_coating_weight,
            predict_cover_adhesive_PA=predict_cover_adhesive_PA,
            predict_cover_coating_weight=predict_cover_coating_weight,
            eval_details=eval_details,
            overall_score=overall_score,
        )

        # 查找满足预测属性值的NART号
        product_property.available_backing_NART = self._find_backing_nart(
            predict_backing_thickness
        )
        product_property.available_open_adhesive_NART = self._find_adhesive_nart(
            predict_open_adhesive_PA
        )
        product_property.available_cover_adhesive_NART = self._find_adhesive_nart(
            predict_cover_adhesive_PA
        )

        return product_property


if __name__ == "__main__":
    obj = InputReverser()

    ret = obj.solver(
        target_open_side_PA=7.1,
        target_cover_side_PA=7.5,
        target_total_thickness=100.0,
    )
    print(ret)
