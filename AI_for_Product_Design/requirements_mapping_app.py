# app.py
# 运行： streamlit run app.py
from pathlib import Path
from typing import Tuple, Dict, Any
import io
import base64
import copy
import pandas as pd
import json
import streamlit as st


# ======= 配置（按你的本机路径与上传文件）=======
PAGE_TITLE = "Requirement ↔ Product Coverage (Streamlit)"

INDICATORS = [
    "Total thickness, without liner (10N; disc:16mm)",
    "Total thickness, without liner (4.0N; disc:10mm)",
    "Holding power/steel, open side (10N; RT)",
    "Peel adhesion/Steel, open side (180° method)",
    "Peel adhesion/Steel, covered side (180° method)",
    "Peel adhesion/ASTM-Steel, open side (180° method)",
    "Peel adhesion/ASTM-Steel, covered side (180° method)",
    "Peel adhesion/PC, open side (180° method)",
    "Peel adhesion/Steel, inside (180° method, ASTM3300)",
    "Peel adhesion/Steel, outside (180° method, ASTM3300)",
]

# 默认需求：带 Target
THICKNESS_INDICATOR = "Total thickness, without liner (10N; disc:16mm)"

PERFORMANCE_CONFIG = {
    "pa_sus_open": {
        "label": "PA To SUS Open Side (N/25mm)",
        "limits": (0.0, 15.0),
        "default": (0.0, 15.0),
        "step": 0.1,
        "indicator": "Peel adhesion/Steel, open side (180° method)",
    },
    "pa_sus_covered": {
        "label": "PA To SUS Covered Side (N/25mm)",
        "limits": (0.0, 15.0),
        "default": (0.0, 15.0),
        "step": 0.1,
        "indicator": "Peel adhesion/Steel, covered side (180° method)",
    },
    "remove_force": {
        "label": "Remove Force (N/25mm)",
        "limits": (0, 50),
        "default": (0, 50),
        "step": 1,
        "indicator": "Holding power/steel, open side (10N; RT)",
    },
    "holding_power": {
        "label": "Holding Power",
        "limits": (0, 3000),
        "default": (0, 3000),
        "step": 1,
        "indicator": "Holding power/steel, open side (10N; RT)",
    },
    "coating_weight_open": {
        "label": "Coating Weight Open Side",
        "limits": (0, 50000),
        "default": (0, 50000),
        "step": 100,
        "indicator": "Coating weight open side",
    },
    "coating_weight_cover": {
        "label": "Coating Weight Cover Side",
        "limits": (0, 50000),
        "default": (0, 50000),
        "step": 100,
        "indicator": "Coating weight cover side",
    },
}

RANGE_PERFORMANCE_KEYS = {
    "remove_force",
    "holding_power",
    "coating_weight_open",
    "coating_weight_cover",
    "pa_sus_open",
    "pa_sus_covered",
}

COLOR_OPTIONS = ["透明", "白色", "蓝色", "红色", "黑色", "绿色"]
MATERIAL_GROUP_OPTIONS = ["胶水", "离型纸", "基材"]
MATERIAL_OPTIONS = {
    "胶水": [],
    "离型纸": [],
    "基材": ["PET", "Foam"],
}
THICKNESS_LIMITS = (0, 500.0)
THICKNESS_DEFAULT_VALUE = 30.0
PRODUCT_TYPE_OPTIONS = ["Single-liner", "Double-liner", "Transfer", "Multi-layer"]


def _make_default_filters():
    return {
        "structure": {
            "product_type": PRODUCT_TYPE_OPTIONS[0],
            "total_thickness": {
                "value": THICKNESS_DEFAULT_VALUE,
            },
            "colors": ["不限"],
            "material_group": "基材",
            "materials": ["PET"],
        },
        "performance": {
            key: {
                (
                    "range"
                    if key in RANGE_PERFORMANCE_KEYS
                    else "value"
                ): cfg["default"],
            }
            for key, cfg in PERFORMANCE_CONFIG.items()
        },
    }


def _make_empty_filters():
    return {
        "structure": {
            "product_type": PRODUCT_TYPE_OPTIONS[0],
            "total_thickness": {
                "value": None,
            },
            "colors": [],
            "material_group": "基材",
            "materials": [],
        },
        "performance": {
            key: {
                (
                    "range"
                    if key in RANGE_PERFORMANCE_KEYS
                    else "value"
                ): None,
            }
            for key, cfg in PERFORMANCE_CONFIG.items()
        },
    }


def _clone_filters(filters: dict) -> dict:
    return copy.deepcopy(filters)


def _filters_to_requirements(filters: dict) -> dict:
    requirements = {
        indicator: {"Target": None, "LB": None, "UB": None} for indicator in INDICATORS
    }

    thickness_cfg = filters.get("structure", {}).get("total_thickness", {})
    target = thickness_cfg.get("value")
    if target is not None:
        requirements.setdefault(
            THICKNESS_INDICATOR, {"Target": None, "LB": None, "UB": None}
        )
        requirements[THICKNESS_INDICATOR]["Target"] = float(target)

    for key, cfg in filters.get("performance", {}).items():
        perf_meta = PERFORMANCE_CONFIG.get(key)
        if not perf_meta:
            continue
        indicator_name = perf_meta["indicator"]
        if key in RANGE_PERFORMANCE_KEYS:
            # 使用范围
            lb_ub = cfg.get("range")
            if lb_ub is None:
                continue
            lb, ub = lb_ub
            if lb is None or ub is None:
                continue
            requirements.setdefault(
                indicator_name, {"Target": None, "LB": None, "UB": None}
            )
            requirements[indicator_name]["LB"] = float(lb)
            requirements[indicator_name]["UB"] = float(ub)
        else:
            # 使用目标值
            value = cfg.get("value")
            if value is None:
                continue
            try:
                float_val = float(value)
            except (TypeError, ValueError):
                continue
            requirements.setdefault(
                indicator_name, {"Target": None, "LB": None, "UB": None}
            )
            requirements[indicator_name]["Target"] = float_val

    return requirements


def _reset_evaluation_state():
    st.session_state.selected_product = None
    st.session_state.step1_result = None
    st.session_state.step1_has_match = False
    st.session_state.step1_selected_spec = None
    st.session_state.step1_meta = {}
    st.session_state.step2_products = None
    st.session_state.step2_radar = None
    st.session_state.step2_error = None
    st.session_state.step2_detail_df = None
    st.session_state.step2_selected_spec = None
    st.session_state.step4_active = False
    st.session_state.step4_result = None
    st.session_state.step4_selected_index = None


# ======= 导入核心函数 =======
from app.search import ProductSearch, Product
from app.input_reverser import InputReverser, ProductPredictedProperty
from app.approximate_search import ApproximateSearch

# ======= Streamlit 基本设置 =======
st.set_page_config(
    page_title=PAGE_TITLE, layout="wide", initial_sidebar_state="collapsed"
)

# ======= 主标题 =======
st.markdown(
    """
    <div style="text-align: center; margin-bottom: 2rem;">
        <h1 style="color: #2c3e50; border-bottom: 2px solid #34495e; padding-bottom: 0.5rem; display: inline-block;">
            PDA - AI for Product Design
        </h1>
        <p style="color: #7f8c8d; margin-top: 0.5rem; font-size: 1rem;">
            产品需求匹配与材料替换建议系统
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ======= 工业化简洁样式 =======
st.markdown(
    """
    <style>
    /* 全局样式 */
    :root {
        /* 覆盖 Streamlit 默认主色（原为红/粉），统一为工业蓝 */
        --primary-color: #34495e;
    }
    
    .st-emotion-cache-1cl4umz{
        background: #34495e;
        border-radius: 4px;
        border: 1px solid #34495e;
    }
    
    .st-emotion-cache-1cl4umz:hover{
        background: #2c3e50;
        border-radius: 4px;
        border: 1px solid #2c3e50;
    }

    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* 标题样式 - 深蓝工业色 */
    h1 {
        color: #2c3e50;
        border-bottom: 2px solid #34495e;
        padding-bottom: 0.5rem;
        margin-bottom: 1.5rem;
    }
    
    h2, h3 {
        color: #34495e;
        margin-top: 1.5rem;
    }
    
    /* Target 列样式 - 简洁黄色背景 */
    .target-col { 
        padding: 0.4rem 0.6rem; 
        background: #fff9e6; 
        border-radius: 4px; 
        border: 1px solid #e0d4a8;
    }
    
    
    
    .target-header { 
        display: inline-block; 
        padding: 0.3rem 0.6rem; 
        background: #f5e6a3; 
        border-radius: 4px; 
        font-weight: 600;
        color: #5a4a2a;
        border: 1px solid #d4c082;
    }
    
    /* 按钮样式 - 简洁工业风格 */
    .stButton > button {
        border-radius: 4px;
        font-weight: 500;
        border: 1px solid #bdc3c7;
    }
    
    .stButton > button:hover {
        border-color: #34495e;
    }
    
    /* 表单输入框样式 */
    .stTextInput > div > div > input {
        border-radius: 4px;
        border: 1px solid #bdc3c7;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #34495e;
        outline: none;
    }
    
    /* Metric 卡片样式 */
    [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 600;
        color: #2c3e50;
    }
    
    [data-testid="stMetricDelta"] {
        font-size: 0.9rem;
        font-weight: 500;
    }
    
    /* 表格样式 - 简洁边框 */
    .dataframe {
        border: 1px solid #e0e0e0;
    }
    
    /* 图片成对展示 */
    .image-pair {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 2rem;
        margin: 1rem 0 1.5rem 0;
    }
    
    .image-pair figure {
        margin: 0;
        text-align: center;
        max-width: 100%;
    }
    
    .image-pair img {
        display: block;
        max-width: 100%;
        height: auto;
        margin: 0 auto;
    }
    
    .image-pair figcaption {
        margin-top: 0.5rem;
        color: #7f8c8d;
        font-size: 0.9rem;
    }
    
    /* 状态标签样式 - 工业配色 */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 3px;
        font-size: 0.85rem;
        font-weight: 500;
    }
    
    .status-satisfied {
        background-color: #d5e8d4;
        color: #2d5016;
        border: 1px solid #82b366;
    }
    
    .status-partial {
        background-color: #ffe6cc;
        color: #7c4a00;
        border: 1px solid #d79b00;
    }
    
    .status-unsatisfied {
        background-color: #f8cecc;
        color: #783f04;
        border: 1px solid #b85450;
    }
    
    /* 步骤指示器 - 深蓝工业色 */
    .step-indicator {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        background: #34495e;
        color: white;
        border-radius: 4px;
        font-weight: 500;
        margin-bottom: 1rem;
        border: 1px solid #2c3e50;
    }
    
    /* 卡片容器 */
    .card-container {
        background: white;
        padding: 1.5rem;
        border-radius: 4px;
        border: 1px solid #e0e0e0;
        margin-bottom: 1rem;
    }
    
    /* 信息提示框 */
    .stInfo {
        border-left: 3px solid #3498db;
    }
    
    /* 警告框 */
    .stWarning {
        border-left: 3px solid #f39c12;
    }
    
    /* 错误框 */
    .stError {
        border-left: 3px solid #e74c3c;
    }
    
    /* 成功提示 */
    .success-message {
        background: #d5e8d4;
        color: #2d5016;
        padding: 1rem;
        border-radius: 4px;
        border-left: 3px solid #82b366;
        margin: 1rem 0;
    }
    
    /* Top 3 产品卡片 - 简洁灰色 */
    .product-card {
        background: #f5f5f5;
        padding: 1rem;
        border-radius: 4px;
        border: 1px solid #bdc3c7;
    }
    
    .product-card:hover {
        border-color: #34495e;
    }
    
    /* 分隔线 - 简洁灰色 */
    hr {
        border: none;
        height: 1px;
        background: #e0e0e0;
        margin: 2rem 0;
    }
    
    /* 选择框样式 */
    .stSelectbox > div > div > select {
        border-radius: 4px;
        border: 1px solid #bdc3c7;
    }
    
    /* 下载按钮样式 - 深蓝 */
    .stDownloadButton > button {
        background: #34495e;
        color: white;
        border: 1px solid #2c3e50;
    }
    
    .stDownloadButton > button:hover {
        background: #2c3e50;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ======= 状态初始化 =======
if "filters" not in st.session_state:
    st.session_state.filters = _clone_filters(_make_default_filters())
if "requirements" not in st.session_state:
    st.session_state.requirements = _filters_to_requirements(st.session_state.filters)
if "selected_product" not in st.session_state:
    st.session_state.selected_product = None
if "step1_result" not in st.session_state:
    st.session_state.step1_result = None
if "step1_has_match" not in st.session_state:
    st.session_state.step1_has_match = False
if "step1_selected_spec" not in st.session_state:
    st.session_state.step1_selected_spec = None
if "step1_meta" not in st.session_state:
    st.session_state.step1_meta = {}
if "step2_products" not in st.session_state:
    st.session_state.step2_products = None
if "step2_radar" not in st.session_state:
    st.session_state.step2_radar = None
if "step2_error" not in st.session_state:
    st.session_state.step2_error = None
if "step2_detail_df" not in st.session_state:
    st.session_state.step2_detail_df = None
if "step2_selected_spec" not in st.session_state:
    st.session_state.step2_selected_spec = None
if "step2_radar" not in st.session_state:
    st.session_state.step2_radar = ""
if "step2_pca" not in st.session_state:
    st.session_state.step2_pca = ""
if "step4_active" not in st.session_state:
    st.session_state.step4_active = False
if "step4_result" not in st.session_state:
    st.session_state.step4_result = None
if "step4_selected_index" not in st.session_state:
    st.session_state.step4_selected_index = None
if "step4_n_best" not in st.session_state:
    st.session_state.step4_n_best = 10
if "step4_n_best_options" not in st.session_state:
    st.session_state.step4_n_best_options = [5, 10, 20, 50, 100]


# ======= 小工具 =======
@st.cache_data(show_spinner=False)
def _load_image_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _parse_float_or_none(s: str):
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _make_scheme_key(row: pd.Series) -> str:
    return f"{row['bom_key']} | {row['change_type']} | {row['from_material']} → {row['to_material']}"


def _style_improve(df_compare: pd.DataFrame):
    def highlight(row):
        styles = []
        for col in row.index:
            if col == "score_delta":
                delta = row.get("score_delta", 0)
                if pd.notna(delta):
                    if delta > 0:
                        styles.append(
                            "background-color: #d5e8d4; color: #2d5016; font-weight: 500;"
                        )
                    elif delta < 0:
                        styles.append(
                            "background-color: #f8cecc; color: #783f04; font-weight: 500;"
                        )
                    else:
                        styles.append("background-color: #f5f5f5;")
                else:
                    styles.append("")
            elif col == "status" or "status" in col.lower():
                val = str(row.get(col, "")).lower()
                if "fully satisfied" in val or "satisfied" in val:
                    styles.append(
                        "background-color: #d5e8d4; color: #2d5016; font-weight: 500;"
                    )
                elif "partially" in val:
                    styles.append(
                        "background-color: #ffe6cc; color: #7c4a00; font-weight: 500;"
                    )
                elif "unsatisfied" in val:
                    styles.append(
                        "background-color: #f8cecc; color: #783f04; font-weight: 500;"
                    )
                else:
                    styles.append("")
            else:
                styles.append("")
        return styles

    return df_compare.style.apply(highlight, axis=1)


def _format_metric(value) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, (int, float)):
        formatted = f"{value:.2f}"
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted
    return str(value)


# ======= 资源缓存 =======
@st.cache_resource(show_spinner=False)
def _get_product_search() -> ProductSearch:
    return ProductSearch()


@st.cache_resource(show_spinner=False)
def _get_input_reverser() -> InputReverser:
    return InputReverser()


# @st.cache_resource(show_spinner=False)
def _get_approximate_search() -> ApproximateSearch:
    return ApproximateSearch()


# ======= 关键步骤函数 =======
def perform_exact_match(filters: dict) -> Tuple[pd.DataFrame, Dict[str, Any], bool]:
    searcher = _get_product_search()

    thickness_lb = thickness_ub = None
    structure_cfg = filters.get("structure", {})
    total_cfg = structure_cfg.get("total_thickness", {})
    value = total_cfg.get("value")
    if value is not None:
        thickness_lb = float(value)
        thickness_ub = float(value)

    performance_cfg = filters.get("performance", {})

    def _value_bounds(
        key: str, limits: tuple[float, float]
    ) -> Tuple[float | None, float | None]:
        cfg = performance_cfg.get(key, {})
        rng = cfg.get("range")
        if rng is None:
            return None, None
        lb, ub = rng
        return float(lb), float(ub)

    def _target_value(key: str) -> Tuple[float | None, float | None]:
        cfg = performance_cfg.get(key, {})
        rng = cfg.get("range")
        if rng is not None:
            lb, ub = rng
            try:
                return float(lb), float(ub)
            except (TypeError, ValueError):
                return None, None
        value = cfg.get("value")
        if value is None:
            return None, None
        try:
            float_val = float(value)
        except (TypeError, ValueError):
            return None, None
        return float_val, float_val

    pa_open_lb, pa_open_ub = _target_value("pa_sus_open")
    pa_cover_lb, pa_cover_ub = _target_value("pa_sus_covered")
    remove_lb, remove_ub = _value_bounds(
        "remove_force", PERFORMANCE_CONFIG["remove_force"]["limits"]
    )

    colours_cfg = structure_cfg.get("colors") or []
    colour_value = colours_cfg[0] if colours_cfg else ""
    material_group = structure_cfg.get("material_group")
    materials = structure_cfg.get("materials") or []
    if material_group != "基材" or not materials:
        backing_material_value = None
    else:
        backing_material_value = materials[0] if materials else None

    results: list[Product] = []
    seen_specs = set()

    base_kwargs = {
        "total_thickness_lb": thickness_lb,
        "total_thickness_ub": thickness_ub,
        "PA_SUS_open_side_lb": pa_open_lb,
        "PA_SUS_open_side_ub": pa_open_ub,
        "PA_SUS_covered_side_lb": pa_cover_lb,
        "PA_SUS_covered_side_ub": pa_cover_ub,
        "Remove_force_lb": remove_lb,
        "Remove_force_ub": remove_ub,
        "colour": colour_value or None,
        "backing_material": None,
        "label": None,
        "limit": None,
    }

    print("1" * 100)
    print("kwargs", base_kwargs)
    try:
        # base_kwargs = {
        #     "total_thickness_lb": 12.0,
        #     "PA_SUS_open_side_lb": 6.0,
        #     "label": None,
        #     "limit": None,
        #     "total_thickness_ub": None,
        #     "colour":None,
        #     "backing_material":None,
        #     "PA_SUS_covered_side_ub":None,
        #     "PA_SUS_covered_side_lb":None,
        #     "PA_SUS_open_side_ub":None,
        #     "Remove_force_ub":None,
        #     "Remove_force_lb":None,
        # }
        # base_kwargs = {
        #     "total_thickness_lb": 30.0,
        #     "total_thickness_ub": 30.0,
        #     "PA_SUS_open_side_lb": 6.3,
        #     "PA_SUS_open_side_ub": 6.3,
        #     "PA_SUS_covered_side_lb": None,
        #     "PA_SUS_covered_side_ub": None,
        #     "Remove_force_lb": None,
        #     "Remove_force_ub": None,
        #     "colour": None,
        #     "backing_material": None,
        #     "label": None,
        #     "limit": None,
        # }

        print("my_base_kwargs", base_kwargs)

        product_list = searcher.search_products(**base_kwargs)
        print("2" * 100)
        # 这里将product_list dict化 然后转成json字符串 然后打印
        product_list_dict = [product.model_dump() for product in product_list]
        product_list_json = json.dumps(product_list_dict)
        print("product_list", product_list_json)
    except Exception as err:
        return (
            pd.DataFrame(
                [
                    {
                        "步骤": "Step 1 · 精确匹配",
                        "说明": f"产品搜索失败：{err}",
                    }
                ]
            ),
            {},
            False,
        )

    for product in product_list:
        if product.NART in seen_specs:
            continue
        seen_specs.add(product.NART)
        results.append(product)

    product_meta: Dict[str, Any] = {
        product.NART: product.model_dump() for product in results
    }
    if not results:
        return (
            pd.DataFrame(
                [
                    {
                        "步骤": "Step 1 · 精确匹配",
                        "说明": "未找到满足全部条件的产品。",
                    }
                ]
            ),
            {},
            False,
        )

    rows = []
    df_ext = searcher.df_product_extended
    for product in results:
        ext_row = df_ext[df_ext["Product_Spec"] == product.NART]
        ext_series = ext_row.iloc[0] if not ext_row.empty else pd.Series(dtype=float)

        open_pa_value = None
        for item_no in ["P4005_target_value", "P4144_target_value"]:
            val = ext_series.get(item_no)
            if pd.notna(val):
                open_pa_value = float(val)
                break

        cover_pa_value = None
        for item_no in ["P4006_target_value", "P4145_target_value"]:
            val = ext_series.get(item_no)
            if pd.notna(val):
                cover_pa_value = float(val)
                break

        total_thickness_value = ext_series.get("P4433_target_value")
        total_thickness_value = (
            float(total_thickness_value) if pd.notna(total_thickness_value) else None
        )

        rows.append(
            {
                "产品规格": product.NART,
                "产品类型": (
                    "Double-liner"
                    if product.product_type == "double_liner"
                    else "Single-liner"
                ),
                "产品标签": ", ".join(product.labels) if product.labels else "-",
                "Liner_NART": product.Liner_NART or "-",
                "In_Liner_NART": product.In_Liner_NART or "-",
                "Out_Liner_NART": product.Out_Liner_NART or "-",
                "Open_Adhesive_NART": product.Open_Adhesive_NART or "-",
                "Cover_Adhesive_NART": product.Cover_Adhesive_NART or "-",
                "Backing_NART": product.Backing_NART or "-",
                "PA To SUS Open Side (N/25mm)": open_pa_value,
                "PA To SUS Covered Side (N/25mm)": cover_pa_value,
                "总厚度 (µm)": total_thickness_value,
            }
        )

    result_df = pd.DataFrame(rows)
    result_df = result_df.sort_values("产品规格").reset_index(drop=True)
    return result_df, product_meta, True


def initiate_new_material_research(
    requirements: dict, filters: dict, n_best: int = 10
) -> list[dict[str, Any]]:
    reverser = _get_input_reverser()

    def _require_target(indicator_key: str, friendly_name: str) -> float:
        record = requirements.get(indicator_key, {})
        print("record",indicator_key, requirements, )
        target_value = record.get("Target")
        if target_value is None:
            lb = record.get("LB")
            ub = record.get("UB")
            if lb is not None:
                target_value = float(lb)
            elif ub is not None:
                target_value = float(ub)
        if target_value is None:
            raise ValueError(f"缺少目标值：{friendly_name}")
        return float(target_value)

    open_indicator = PERFORMANCE_CONFIG["pa_sus_open"]["indicator"]
    cover_indicator = PERFORMANCE_CONFIG["pa_sus_covered"]["indicator"]
    target_total_thickness = _require_target(
        THICKNESS_INDICATOR, "总厚度 (不含离型纸)"
    )

    performance_cfg = filters.get("performance", {})
    
    print("performance_cfg", performance_cfg)

    def _optional_range(key: str) -> Tuple[float | None, float | None]:
        cfg = performance_cfg.get(key, {})
        rng = cfg.get("range")
        if rng is None:
            value = cfg.get("value")
            if value is None:
                return None, None
            try:
                float_val = float(value)
            except (TypeError, ValueError):
                return None, None
            return float_val, float_val
        try:
            return rng[0], rng[1]
        except Exception:
            return None, None
        
        
    target_open_pa,target_open_pa_r = _optional_range("pa_sus_open")
    target_cover_pa,target_cover_pa_r = _optional_range("pa_sus_covered")
    
    if target_open_pa!=target_open_pa_r or target_cover_pa!=target_cover_pa_r:
        st.error("当前预测方案仅支持目标单值匹配，范围匹配参见后续版本")
        st.stop()
        
    cover_coating_lb, cover_coating_ub = _optional_range("coating_weight_cover")
    open_coating_lb, open_coating_ub = _optional_range("coating_weight_open")
    print("3" * 100)
    print(
        "param",
        {
            "product_open_side_PA": target_open_pa,
            "product_cover_side_PA": target_cover_pa,
            "product_total_thickness": target_total_thickness,
            "cover_coating_weight_lb": cover_coating_lb,
            "cover_coating_weight_ub": cover_coating_ub,
            "open_coating_weight_lb": open_coating_lb,
            "open_coating_weight_ub": open_coating_ub,
        },
    )
    result_list: list[ProductPredictedProperty] = reverser.search_feature_comb(
        product_open_side_PA=target_open_pa,
        product_cover_side_PA=target_cover_pa,
        product_total_thickness=target_total_thickness,
        n_best=n_best,
        cover_coating_weight_lb=cover_coating_lb,
        cover_coating_weight_ub=cover_coating_ub,
        open_coating_weight_lb=open_coating_lb,
        open_coating_weight_ub=open_coating_ub,
    )
    print("4" * 100)
    # 将resultlist 转换成 dict[str, Any] 在变成json打印
    result_list_dict = [item.model_dump() for item in result_list]
    print("result_list_dict", json.dumps(result_list_dict))

    if not result_list:
        return []

    combos: list[dict[str, Any]] = []
    for item in result_list:
        combo = item.model_dump()
        combo["target_open_adhesive_PA"] = round(target_open_pa, 4)
        combo["target_cover_adhesive_PA"] = round(target_cover_pa, 4)
        combo["target_total_thickness"] = round(target_total_thickness, 4)
        if cover_coating_lb is not None or cover_coating_ub is not None:
            combo["target_cover_coating_range"] = (
                round(cover_coating_lb, 2) if cover_coating_lb is not None else None,
                round(cover_coating_ub, 2) if cover_coating_ub is not None else None,
            )
        if open_coating_lb is not None or open_coating_ub is not None:
            combo["target_open_coating_range"] = (
                round(open_coating_lb, 2) if open_coating_lb is not None else None,
                round(open_coating_ub, 2) if open_coating_ub is not None else None,
            )
        # 便于前端展示顺序，将数值统一四舍五入
        for key, value in list(combo.items()):
            if isinstance(value, float):
                combo[key] = round(value, 6)
        combos.append(combo)

    return combos


# ======= 左右布局 =======
left_col, right_col = st.columns([1, 2])

# ---------------- 左侧：需求输入 ----------------
with left_col:
    st.markdown(
        '<div class="step-indicator">配置筛选条件</div>', unsafe_allow_html=True
    )

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("填充默认筛选", use_container_width=True):
            st.session_state.filters = _clone_filters(_make_default_filters())
            st.session_state.requirements = _filters_to_requirements(
                st.session_state.filters
            )
            _reset_evaluation_state()
            st.success("已恢复默认筛选条件！")
    with b2:
        if st.button("清空条件", use_container_width=True):
            st.session_state.filters = _clone_filters(_make_empty_filters())
            st.session_state.requirements = _filters_to_requirements(
                st.session_state.filters
            )
            _reset_evaluation_state()
            st.info("已清空所有筛选条件！")

    st.markdown(
        '<p style="color: #555; font-size: 0.9rem; margin-top: 0.5rem; padding: 0.75rem; background: #f5f5f5; border-radius: 4px; border-left: 3px solid #34495e;">'
        "<strong>提示：</strong>填写数值即启用对应条件；留空或选择全范围即为不限，颜色与材料支持多选组合。"
        "</p>",
        unsafe_allow_html=True,
    )

    current_filters = _clone_filters(st.session_state.filters)

    performance_inputs = {}
    st.markdown('<div class="left-filter-scope">', unsafe_allow_html=True)
    with st.form("filter_form"):
        st.markdown("**By 产品类型**")
        product_type = st.selectbox(
            "Product Type",
            options=PRODUCT_TYPE_OPTIONS,
            index=PRODUCT_TYPE_OPTIONS.index(
                current_filters["structure"].get(
                    "product_type", PRODUCT_TYPE_OPTIONS[0]
                )
            ),
        )
        st.markdown("**By 构造属性**")
        total_cfg = current_filters["structure"]["total_thickness"]
        total_value_input = st.text_input(
            "总厚度 (μm)",
            value=(
                f"{float(total_cfg['value']):g}"
                if total_cfg.get("value") is not None
                else ""
            ),
            placeholder="",
        )

        color_options = ["不限"] + COLOR_OPTIONS
        default_color = (
            current_filters["structure"]["colors"][0]
            if current_filters["structure"]["colors"]
            else "不限"
        )
        selected_color = st.selectbox(
            "颜色",
            options=color_options,
            index=(
                color_options.index(default_color)
                if default_color in color_options
                else 0
            ),
        )

        # 选择主选项
        material_group = st.selectbox(
            "选择材料",
            options=["基材", "胶水", "离型纸"],
            key="main_selectbox",
        )

        selected_materials: list[str] = []
        if material_group == "基材":
            available_materials = MATERIAL_OPTIONS["基材"]
            default_materials = [
                m
                for m in current_filters["structure"].get("materials", [])
                if m in available_materials
            ]
            if not default_materials and available_materials:
                default_materials = [available_materials[0]]
            selected_materials = st.multiselect(
                "选择材料类型（可多选）",
                options=available_materials,
                default=default_materials,
                key="secondary_multiselect",
                help="至少选择一种基材；如不选择则视为不限。",
            )
        else:
            st.selectbox(
                "选择材料（当前仅支持基材）",
                options=["胶水", "离型纸", "基材"],
                index=["胶水", "离型纸"].index(material_group),
                disabled=True,
                key="disabled_selectbox",
            )

        # # 显示选中的材料
        # st.write(f"您选择的材料是: {material_group}")
        # if selected_materials:
        #     st.write(f"您选择的材料类型是: {', '.join(selected_materials)}")
        # else:
        #     st.write("您当前未选择具体材料类型。")

        st.markdown("**By 性能值**")
        for key, meta in PERFORMANCE_CONFIG.items():
            if key in {
                "pa_sus_open",
                "pa_sus_covered",
            }:
                limits = (0.0, 15.0)
                stored_range = current_filters["performance"][key].get("range")
                if stored_range is None:
                    current_range = limits
                else:
                    current_range = (
                        float(stored_range[0]),
                        float(stored_range[1]),
                    )
                range_value = st.slider(
                    meta["label"],
                    min_value=limits[0],
                    max_value=limits[1],
                    value=current_range,
                    step=0.1,
                    help="拖动滑条设置上下限，范围 0~15。",
                )
                performance_inputs[key] = {"range": range_value}
            elif key in RANGE_PERFORMANCE_KEYS:
                limits = tuple(float(v) for v in meta["limits"])
                stored_range = current_filters["performance"][key].get("range")
                if stored_range is None:
                    current_range = limits
                else:
                    current_range = tuple(map(float, stored_range))
                perf_range = st.slider(
                    meta["label"],
                    min_value=limits[0],
                    max_value=limits[1],
                    value=current_range,
                    step=float(meta["step"]),
                    help="拖动至全范围即为不限",
                )
                performance_inputs[key] = {"range": perf_range}
            else:
                current_value = current_filters["performance"][key]["value"]
                perf_value_input = st.text_input(
                    meta["label"],
                    value=(
                        f"{float(current_value):g}" if current_value is not None else ""
                    ),
                    placeholder="",
                )
                performance_inputs[key] = {"value": perf_value_input}

        submitted = st.form_submit_button(
            "计算匹配结果", use_container_width=True, type="primary"
        )
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------- 右侧：执行流程展示 ----------------
with right_col:
    st.markdown(
        '<div class="step-indicator">Step 1 · 精确匹配</div>', unsafe_allow_html=True
    )

    if submitted:
        updated_filters = _clone_filters(st.session_state.filters)
        updated_filters["structure"]["product_type"] = product_type
        total_value_str = (total_value_input or "").strip()
        if total_value_str == "":
            updated_filters["structure"]["total_thickness"]["value"] = None
        else:
            parsed_total = _parse_float_or_none(total_value_str)
            if parsed_total is None:
                st.error("总厚度需输入数值")
                st.stop()
            if not (THICKNESS_LIMITS[0] <= parsed_total <= THICKNESS_LIMITS[1]):
                st.error(
                    f"总厚度需在 {THICKNESS_LIMITS[0]} ~ {THICKNESS_LIMITS[1]} 范围内"
                )
                st.stop()
            updated_filters["structure"]["total_thickness"]["value"] = float(
                parsed_total
            )
        if selected_color == "不限":
            updated_filters["structure"]["colors"] = []
        else:
            updated_filters["structure"]["colors"] = [selected_color]
        updated_filters["structure"]["material_group"] = material_group
        if material_group == "基材":
            updated_filters["structure"]["materials"] = selected_materials or []
        else:
            # 切走非“基材”时保留之前选择，避免用户切回后丢失
            updated_filters["structure"]["materials"] = st.session_state.filters.get("structure", {}).get("materials", [])

        for key, val in performance_inputs.items():
            if key.endswith("_slider_changed"):
                continue
            limits = PERFORMANCE_CONFIG[key]["limits"]
            if key in RANGE_PERFORMANCE_KEYS:
                range_value = tuple(float(v) for v in val["range"])
                full_range = (
                    abs(range_value[0] - limits[0]) < 1e-9
                    and abs(range_value[1] - limits[1]) < 1e-9
                )
                if full_range and key in {"pa_sus_open", "pa_sus_covered"}:
                    updated_filters["performance"][key]["range"] = limits
                else:
                    updated_filters["performance"][key]["range"] = (
                        None if full_range else range_value
                    )
            else:
                value_str = (val["value"] or "").strip()
                if value_str == "":
                    updated_filters["performance"][key]["value"] = None
                else:
                    parsed_value = _parse_float_or_none(value_str)
                    if parsed_value is None:
                        st.error(f"{PERFORMANCE_CONFIG[key]['label']} 需输入数值")
                        st.stop()
                    if not (limits[0] <= parsed_value <= limits[1]):
                        st.error(
                            f"{PERFORMANCE_CONFIG[key]['label']} 需在 {limits[0]} ~ {limits[1]} 范围内"
                        )
                        st.stop()
                    updated_filters["performance"][key]["value"] = float(parsed_value)

        st.session_state.filters = updated_filters
        st.session_state.requirements = _filters_to_requirements(updated_filters)
        _reset_evaluation_state()
        # 立即触发二次渲染，确保左侧控件按最新 filters 显示，避免用户看到旧值“闪回”
        st.rerun()

    requirements = st.session_state.requirements

    if st.session_state.step1_result is None:
        with st.spinner("正在执行精确匹配..."):
            try:
                (
                    step1_df,
                    step1_meta,
                    step1_has_match,
                ) = perform_exact_match(st.session_state.filters)
                st.session_state.step1_result = step1_df
                st.session_state.step1_meta = step1_meta
                st.session_state.step1_has_match = step1_has_match
                if (
                    isinstance(st.session_state.step1_result, pd.DataFrame)
                    and not st.session_state.step1_result.empty
                    and "产品规格" in st.session_state.step1_result.columns
                ):
                    st.session_state.step1_selected_spec = (
                        st.session_state.step1_result.iloc[0]["产品规格"]
                    )
                else:
                    st.session_state.step1_selected_spec = None
            except Exception as err:
                st.error(f"精确匹配执行失败：{err}")
                st.session_state.step1_result = pd.DataFrame(
                    [
                        {
                            "步骤": "Step 1 · 精确匹配",
                            "说明": "执行失败，请稍后重试。",
                        }
                    ]
                )
                st.session_state.step1_has_match = False
                st.session_state.step1_meta = {}

    step1_result = st.session_state.step1_result
    if isinstance(step1_result, pd.DataFrame):
        if step1_result.empty:
            st.info("精确匹配暂无结果。")
        elif "产品规格" not in step1_result.columns:
            st.dataframe(step1_result, width="stretch", hide_index=True)
        else:
            summary_df = step1_result.fillna(pd.NA).reset_index(drop=True)
            option_items = []
            for _, row in summary_df.iterrows():
                spec = row["产品规格"]
                thickness = _format_metric(row.get("总厚度 (µm)"))
                open_pa = _format_metric(row.get("PA To SUS Open Side (N/25mm)"))
                cover_pa = _format_metric(row.get("PA To SUS Covered Side (N/25mm)"))
                label = f"{spec} ｜ 总厚度 {thickness} µm ｜ PA To SUS Open Side {open_pa} ｜ PA To SUS Covered Side  {cover_pa}"
                option_items.append((spec, label))

            if not option_items:
                st.info("精确匹配暂无可选产品。")
            else:
                total_matches = len(option_items)
                st.markdown("**结论汇总**")

                st.write(
                    f"精确筛选匹配到 {total_matches} 项产品，请选择其中 1 条在下方查看详情。"
                )
                default_index = 0
                for idx, (spec, _) in enumerate(option_items):
                    if spec == st.session_state.step1_selected_spec:
                        default_index = idx
                        break
                labels = [label for _, label in option_items]
                default_index = max(0, min(default_index, len(labels) - 1))
                st.markdown("**匹配产品列表**")
                # 选择产品不需要标题，默认选中第一个
                st.markdown(
                    """
                    <style>
                    div[data-testid="stRadio"] > label {display: none;}
                    div[data-testid="stRadio"] {margin-top: -15px;}
                    </style>
                """,
                    unsafe_allow_html=True,
                )
                selected_label = st.radio(
                    "",
                    options=labels,
                    index=default_index,
                    key="step1_selection",
                    label_visibility="collapsed",
                )
                selected_spec = next(
                    spec for spec, label in option_items if label == selected_label
                )
                st.session_state.step1_selected_spec = selected_spec

                detail_row = summary_df[summary_df["产品规格"] == selected_spec]
                if not detail_row.empty:
                    info_display = detail_row.reset_index(drop=True).apply(
                        lambda col: col.map(_format_metric)
                    )
                    st.markdown("**匹配产品详情**")
                    st.dataframe(
                        info_display,
                        width="stretch",
                        hide_index=True,
                    )

                product_meta = st.session_state.step1_meta.get(selected_spec, {})
                prop_records = product_meta.get("properties") or []
                if prop_records:
                    prop_df = pd.DataFrame(prop_records)
                    prop_df = prop_df.rename(
                        columns={
                            "name": "name",
                            "description": "description",
                            "lb": "lb",
                            "ub": "ub",
                            "value": "value",
                        }
                    )

                    def _split_desc_and_unit(raw: Any) -> tuple[str, str]:
                        text = str(raw) if raw is not None else ""
                        if "##" not in text:
                            return text, "-"
                        parts = [segment for segment in text.split("##") if segment]
                        if not parts:
                            return text, "-"
                        base = parts[0]
                        unit = parts[-1] if len(parts) > 1 else "-"
                        return base, unit

                    desc_unit_series = prop_df["description"].apply(
                        _split_desc_and_unit
                    )
                    prop_df["description"] = desc_unit_series.apply(lambda x: x[0])
                    prop_df["unit"] = desc_unit_series.apply(lambda x: x[1])
                    prop_df = prop_df.apply(lambda col: col.map(_format_metric))
                    st.markdown("**properties**")
                    st.dataframe(
                        prop_df,
                        width="stretch",
                        hide_index=True,
                    )
                    labels = product_meta.get("labels") or []
                else:
                    st.info("该产品暂无属性数据可展示。")
    elif step1_result is not None: 
        st.write(step1_result)
    else:
        st.info("暂未生成精确匹配结果，请点击左侧“计算匹配结果”。")

    st.divider()
    st.markdown(
        '<div class="step-indicator">Step 2 · 近似匹配</div>', unsafe_allow_html=True
    )

    if st.session_state.step1_has_match:
        st.info("已找到精确匹配的方案，本轮将跳过最接近产品推荐与后续设计步骤。")
    else:
        filters_cfg = st.session_state.filters
        structure_cfg = filters_cfg.get("structure", {})
        performance_cfg = filters_cfg.get("performance", {})

        def _as_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        total_cfg = structure_cfg.get("total_thickness", {})
        total_val = _as_float(total_cfg.get("value"))
        total_lb = total_val
        total_ub = total_val

        def _value_bounds(key: str):
            cfg = performance_cfg.get(key, {})
            value = _as_float(cfg.get("value"))
            if value is None:
                return None, None
            return value, value

        def _range_bounds(key: str):
            cfg = performance_cfg.get(key, {})
            rng = cfg.get("range")
            if not rng:
                return None, None
            lb = _as_float(rng[0])
            ub = _as_float(rng[1])
            return lb, ub

        pa_open_lb, pa_open_ub = _range_bounds("pa_sus_open")
        pa_cover_lb, pa_cover_ub = _range_bounds("pa_sus_covered")
        remove_lb, remove_ub = _range_bounds("remove_force")
        holding_lb, holding_ub = _range_bounds("holding_power")
        cover_weight_lb, cover_weight_ub = _range_bounds("coating_weight_cover")
        open_weight_lb, open_weight_ub = _range_bounds("coating_weight_open")

        colour_input = [c for c in (structure_cfg.get("colors") or []) if c] or None

        if (
            st.session_state.step2_products is None
            and st.session_state.step2_error is None
        ):
            with st.spinner("正在执行近似匹配..."):
                try:
                    approx_search = _get_approximate_search()
                    print("5" * 100)
                    print(
                        "param",
                        {
                            "total_thickness_lb": total_lb,
                            "total_thickness_ub": total_ub,
                            "colour": colour_input,
                            "PA_SUS_open_side_lb": pa_open_lb,
                            "PA_SUS_open_side_ub": pa_open_ub,
                            "PA_SUS_covered_side_lb": pa_cover_lb,
                            "PA_SUS_covered_side_ub": pa_cover_ub,
                            "Remove_force_lb": remove_lb,
                            "Remove_force_ub": remove_ub,
                            "Holding_Power_lb": holding_lb,
                            "Holding_Power_ub": holding_ub,
                            "cover_coating_weight_lb": cover_weight_lb,
                            "cover_coating_weight_ub": cover_weight_ub,
                            "open_coating_weight_lb": open_weight_lb,
                            "open_coating_weight_ub": open_weight_ub,
                        },
                    )
                    (
                        products,
                        radar_image,
                    ) = approx_search.approximate_product_search(
                        total_thickness_lb=total_lb,
                        total_thickness_ub=total_ub,
                        colour=colour_input,
                        PA_SUS_open_side_lb=pa_open_lb,
                        PA_SUS_open_side_ub=pa_open_ub,
                        PA_SUS_covered_side_lb=pa_cover_lb,
                        PA_SUS_covered_side_ub=pa_cover_ub,
                        Remove_force_lb=remove_lb,
                        Remove_force_ub=remove_ub,
                        Holding_Power_lb=holding_lb,
                        Holding_Power_ub=holding_ub,
                        cover_coating_weight_lb=cover_weight_lb,
                        cover_coating_weight_ub=cover_weight_ub,
                        open_coating_weight_lb=open_weight_lb,
                        open_coating_weight_ub=open_weight_ub,
                    )
                    pca_image = approx_search.draw_product_PCA(
                        total_thickness_lb=total_lb,
                        total_thickness_ub=total_ub,
                        colour=colour_input,
                        PA_SUS_open_side_lb=pa_open_lb,
                        PA_SUS_open_side_ub=pa_open_ub,
                        PA_SUS_covered_side_lb=pa_cover_lb,
                        PA_SUS_covered_side_ub=pa_cover_ub,
                        Remove_force_lb=remove_lb,
                        Remove_force_ub=remove_ub,
                        Holding_Power_lb=holding_lb,
                        Holding_Power_ub=holding_ub,
                        cover_coating_weight_lb=cover_weight_lb,
                        cover_coating_weight_ub=cover_weight_ub,
                        open_coating_weight_lb=open_weight_lb,
                        open_coating_weight_ub=open_weight_ub,
                    )
                    print("6" * 100)
                    # 这里将product dict化 然后转成json字符串 然后打印
                    products_dict = [product.model_dump() for product in products]
                    products_json = json.dumps(products_dict)
                    print("products", products_json)
                    st.session_state.step2_products = products
                    st.session_state.step2_radar = radar_image
                    st.session_state.step2_pca = pca_image
                    st.session_state.step2_error = None
                except Exception as err:
                    st.session_state.step2_products = []
                    st.session_state.step2_radar = ""
                    st.session_state.step2_pca = ""
                    st.session_state.step2_error = str(err)
                    st.session_state.selected_product = None
                    st.session_state.step2_selected_spec = None
                    st.session_state.step2_detail_df = None

        approx_error = st.session_state.step2_error
        approx_products = st.session_state.step2_products or []
        radar_b64 = st.session_state.step2_radar or ""
        pca_b64 = st.session_state.step2_pca or ""

        def _launch_new_material_research():
            st.session_state.step4_active = False
            st.session_state.step4_result = None
            st.session_state.step4_selected_index = None
            try:
                st.session_state.step4_result = initiate_new_material_research(
                    requirements,
                    st.session_state.filters,
                    n_best=st.session_state.step4_n_best,
                )
                st.session_state.step4_active = True
                if (
                    isinstance(st.session_state.step4_result, pd.DataFrame)
                    and not st.session_state.step4_result.empty
                    and "similarity_score" in st.session_state.step4_result.columns
                ):
                    st.session_state.step4_selected_index = 0
                else:
                    st.session_state.step4_selected_index = None
            except ValueError as err:
                st.error(f"新材料研发失败：{err}")
                st.session_state.step4_active = False
                st.session_state.step4_result = None
                st.session_state.step4_selected_index = None
            except Exception as err:
                st.error(f"新材料研发执行异常：{err}")
                st.session_state.step4_active = False
                st.session_state.step4_result = None
                st.session_state.step4_selected_index = None

        if approx_error:
            st.error(f"近似匹配执行失败：{approx_error}")
            st.session_state.selected_product = None
            st.session_state.step2_selected_spec = None
        elif not approx_products:
            st.info("近似匹配暂无结果。")
            st.session_state.selected_product = None
            st.session_state.step2_selected_spec = None
            st.session_state.step2_detail_df = None
            if st.button(
                "未找到满足需求的产品，继续探索新的材料组合",
                key="trigger_step3_no_candidates",
                use_container_width=True,
            ):
                _launch_new_material_research()
        else:
            products_sorted = sorted(
                approx_products,
                key=lambda p: p.match_score if p.match_score is not None else 0.0,
                reverse=True,
            )
            total_matches = len(products_sorted)
            best_score_value = max(
                (p.match_score or 0.0 for p in products_sorted),
                default=0.0,
            )
            st.markdown("**结论汇总**")
            st.write(
                f"检索到 {total_matches} 项最相近产品，最高相似评分 {best_score_value:.1f}，请在下方选择查看详细评估。"
            )

            c_img1, c_img2 = st.columns(2)
            with c_img1:
                if radar_b64:
                    try:
                        radar_bytes = base64.b64decode(radar_b64)
                        st.image(
                            io.BytesIO(radar_bytes),
                            caption="Radar 分布示意",
                            width="stretch",
                        )
                    except Exception:
                        pass
            with c_img2:
                if pca_b64:
                    try:
                        pca_bytes = base64.b64decode(pca_b64)
                        st.image(
                            io.BytesIO(pca_bytes),
                            caption="PCA密度分布示意",
                            width="stretch",
                        )
                    except Exception:
                        pass

            summary_rows = []
            for product in products_sorted:
                match_score = product.match_score or 0.0
                summary_rows.append(
                    {
                        "product_spec": product.product_spec,
                        "match_score": match_score,
                        "product_type": (
                            "Double-liner"
                            if product.product_type == "double_liner"
                            else "Single-liner"
                        ),
                        "liner_nart": product.Liner_NART or "-",
                        "in_liner_nart": product.In_Liner_NART or "-",
                        "out_liner_nart": product.Out_Liner_NART or "-",
                        "open_adhesive_nart": product.Open_Adhesive_NART or "-",
                        "cover_adhesive_nart": product.Cover_Adhesive_NART or "-",
                        "backing_nart": product.Backing_NART or "-",
                    }
                )

            specs = [row["product_spec"] for row in summary_rows]
            if (
                st.session_state.step2_selected_spec is None
                or st.session_state.step2_selected_spec not in specs
            ):
                st.session_state.step2_selected_spec = specs[0]

            default_index = next(
                (
                    idx
                    for idx, spec in enumerate(specs)
                    if spec == st.session_state.step2_selected_spec
                ),
                0,
            )
            default_index = max(0, min(default_index, len(specs) - 1))

            def _radio_label(idx: int) -> str:
                row = summary_rows[idx]
                return f"{row['product_spec']} ｜ 匹配度 {row['match_score']:.1f}%"

            st.markdown(
                """
                <style>
                div[data-testid="stRadio"] > label {display: none;}
                div[data-testid="stRadio"] {margin-top: -15px;}
                </style>
            """,
                unsafe_allow_html=True,
            )
            selected_index = st.radio(
                "",
                options=list(range(len(summary_rows))),
                format_func=_radio_label,
                index=default_index,
                key="step2_product_select",
                label_visibility="collapsed",
            )

            selected_product_obj = products_sorted[selected_index]
            selected_spec = selected_product_obj.product_spec
            previous_spec = st.session_state.step2_selected_spec
            st.session_state.step2_selected_spec = selected_spec
            if st.session_state.selected_product != selected_spec:
                st.session_state.selected_product = selected_spec
            if previous_spec != selected_spec:
                st.session_state.step4_active = False
                st.session_state.step4_result = None
                st.session_state.step4_selected_index = None

            st.markdown("**匹配产品列表**")
            selected_summary = pd.DataFrame(
                [
                    {
                        "产品规格": summary_rows[selected_index]["product_spec"],
                        "匹配度": f"{summary_rows[selected_index]['match_score']:.1f}%",
                        "产品类型": summary_rows[selected_index]["product_type"],
                        "Liner_NART": summary_rows[selected_index]["liner_nart"],
                        "In_Liner_NART": summary_rows[selected_index]["in_liner_nart"],
                        "Out_Liner_NART": summary_rows[selected_index][
                            "out_liner_nart"
                        ],
                        "Open_Adhesive_NART": summary_rows[selected_index][
                            "open_adhesive_nart"
                        ],
                        "Cover_Adhesive_NART": summary_rows[selected_index][
                            "cover_adhesive_nart"
                        ],
                        "Backing_NART": summary_rows[selected_index]["backing_nart"],
                    }
                ]
            )
            st.dataframe(
                selected_summary,
                width="stretch",
                hide_index=True,
            )

            detail_rows = []
            for search_prop in selected_product_obj.properties:
                prop = search_prop.property
                detail_rows.append(
                    {
                        "item_no": prop.item_no or "-",
                        "property_name": prop.property_name or "-",
                        "product_value": prop.property_value,
                        "test_method": prop.test_method or "-",
                        "expect_lb": search_prop.expect_value_lb,
                        "expect_ub": search_prop.expect_value_ub,
                        "match_score": search_prop.match_score,
                    }
                )

            detail_columns = [
                "item_no",
                "property_name",
                "product_value",
                "test_method",
                "expect_lb",
                "expect_ub",
                "match_score",
            ]
            detail_df_display = pd.DataFrame(detail_rows, columns=detail_columns)

            if not detail_df_display.empty:
                for col in ["product_value", "expect_lb", "expect_ub"]:
                    if col in detail_df_display:
                        detail_df_display[col] = detail_df_display[col].map(
                            _format_metric
                        )
                if "match_score" in detail_df_display:
                    detail_df_display["match_score"] = detail_df_display[
                        "match_score"
                    ].apply(lambda v: f"{v:.1f}%" if v is not None else "-")

            st.markdown("**匹配产品详情**")
            st.dataframe(
                detail_df_display,
                width="stretch",
                hide_index=True,
            )

            if st.button(
                "以上方案不满足我的需求，我想重新探索新的材料组合",
                key="trigger_step3",
                use_container_width=True,
            ):
                _launch_new_material_research()

        # st.divider()
        # Step 3 展示：与是否选中产品无关，只要有组合结果就呈现
        if st.session_state.step4_active and st.session_state.step4_result is not None:
            st.markdown("---")
            st.markdown(
                '<div class="step-indicator">Step 3 · 新材料研发</div>',
                unsafe_allow_html=True,
            )
            
            col_step3_select, col_step3_reset = st.columns([2, 1])
            with col_step3_select:
                prev_n_best = st.session_state.step4_n_best
                st.session_state.step4_n_best = st.selectbox(
                    "推荐组合数量",
                    options=st.session_state.step4_n_best_options,
                    index=st.session_state.step4_n_best_options.index(
                        st.session_state.step4_n_best
                    )
                    if st.session_state.step4_n_best
                    in st.session_state.step4_n_best_options
                    else st.session_state.step4_n_best_options.index(10),
                    key="step3_n_best_select",
                )
                if st.session_state.step4_n_best != prev_n_best:
                    try:
                        st.session_state.step4_result = initiate_new_material_research(
                            requirements,
                            st.session_state.filters,
                            n_best=st.session_state.step4_n_best,
                        )
                        st.session_state.step4_active = True
                        st.session_state.step4_selected_index = 0
                    except Exception as err:
                        st.error(f"新材料研发失败：{err}")
                        st.session_state.step4_active = False
                        st.session_state.step4_result = None
                        st.session_state.step4_selected_index = None
            step4_result = st.session_state.step4_result
            combos_raw: list[dict[str, Any]] = []
            if isinstance(step4_result, pd.DataFrame):
                combos_raw = step4_result.to_dict("records")
            elif isinstance(step4_result, list):
                combos_raw = step4_result
            else:
                st.write(step4_result)
                combos_raw = []

            if combos_raw:
                for combo in combos_raw:
                    combo.setdefault("eval_details", [])

                total_combos = len(combos_raw)
                best_score = max(
                    (
                        combo.get("overall_score")
                        for combo in combos_raw
                        if isinstance(combo.get("overall_score"), (int, float))
                    ),
                    default=None,
                )
                best_score_str = (
                    f"{best_score*100:.1f}" if best_score is not None else "-"
                )
                st.markdown("**结论汇总**")
                st.write(
                    f"检索到 {total_combos} 项可选的材料设计方案，最高评分预计可达 {best_score_str}%，请在下方选择查看详细评估。"
                )

                def _combo_summary(idx: int, combo: dict) -> dict:
                    score = combo.get("overall_score")
                    score_str = (
                        f"{float(score)*100:.1f}%"
                        if isinstance(score, (int, float))
                        else "-"
                    )
                    return {
                        "组合": f"组合_{idx}",
                        "overall_score": (
                            score if isinstance(score, (int, float)) else None
                        ),
                        "匹配度": score_str,
                        "predict_backing_thickness": combo.get(
                            "predict_backing_thickness"
                        )
                        or combo.get("backing_thickness"),
                        "predict_cover_coating_weight": combo.get(
                            "predict_cover_coating_weight"
                        )
                        or combo.get("cover_coating_weight"),
                        "predict_open_coating_weight": combo.get(
                            "predict_open_coating_weight"
                        )
                        or combo.get("open_coating_weight"),
                        "predict_open_adhesive_PA": combo.get(
                            "predict_open_adhesive_PA"
                        ),
                        "predict_cover_adhesive_PA": combo.get(
                            "predict_cover_adhesive_PA"
                        ),
                    }

                summary_rows = [
                    _combo_summary(idx, combo) for idx, combo in enumerate(combos_raw)
                ]
                default_index = st.session_state.step4_selected_index or 0
                default_index = max(0, min(default_index, len(summary_rows) - 1))

                def _radio_label(idx: int) -> str:
                    row = summary_rows[idx]
                    score = (
                        f"{row['overall_score']*100:.1f}%"
                        if row.get("overall_score") is not None
                        else row["匹配度"]
                    )
                    return f"{row['组合']} ｜ 匹配度 {score}"

                selected_index = st.radio(
                    "",
                    options=list(range(len(summary_rows))),
                    format_func=_radio_label,
                    index=default_index,
                    key="step3_selection",
                    label_visibility="collapsed",
                )
                st.session_state.step4_selected_index = selected_index

                selected_combo = combos_raw[selected_index]

                def _cell_join(label: str, value: float | None) -> str:
                    val_str = _format_metric(value) if value is not None else "-"
                    return f"{label}{val_str}"

                def _adhesive_cell(weight_value, pa_value) -> str:
                    weight_str = _cell_join("coating_weight:", weight_value)
                    pa_str = _cell_join("PA:", pa_value)
                    return f"{pa_str}<br>{weight_str}"

                selected_combo = combos_raw[selected_index]
                plan_name = summary_rows[selected_index]["组合"]
                cover_cell = _adhesive_cell(
                    summary_rows[selected_index]["predict_cover_coating_weight"],
                    summary_rows[selected_index]["predict_cover_adhesive_PA"],
                )
                open_cell = _adhesive_cell(
                    summary_rows[selected_index]["predict_open_coating_weight"],
                    summary_rows[selected_index]["predict_open_adhesive_PA"],
                )
                backing_cell = _cell_join(
                    "thickness:",
                    summary_rows[selected_index]["predict_backing_thickness"],
                )
                final_score = summary_rows[selected_index]["匹配度"]
                open_nart = "<br>".join( selected_combo.get("available_open_adhesive_NART", ["-"]))
                cover_nart = "<br>".join( selected_combo.get("available_cover_adhesive_NART", ["-"]))
                backing_nart = "<br>".join( selected_combo.get("available_backing_NART", ["-"]))
                if summary_rows[selected_index].get("overall_score") is not None:
                    final_score = (
                        f"{summary_rows[selected_index]['overall_score']*100:.1f}%"
                    )

                combo_table_html = f"""
                <table class="combo-overview-table">
                    <thead>
                        <tr>
                            <th>Plan Name</th>
                            <th>Open Side Adhesive</th>
                            <th>Cover Side Adhesive</th>
                            <th>Backing</th>
                            <th>Liner</th>
                            <th>Final Score</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>{plan_name}</td>
                            <td>{open_cell}</td>
                            <td>{cover_cell}</td>
                            <td>{backing_cell}</td>
                            <td>-</td>
                            <td>{final_score}</td>
                        </tr>
                        <tr>
                            <td>适用 NART</td>
                            <td>{open_nart}</td>
                            <td>{cover_nart}</td>
                            <td>{backing_nart}</td>
                            <td>-</td>
                            <td>-</td>
                        </tr>
                    </tbody>
                </table>
                <style>
                .combo-overview-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-bottom: 1rem;
                }}
                .combo-overview-table th,
                .combo-overview-table td {{
                    border: 1px solid #bdc3c7;
                    padding: 0.6rem 0.8rem;
                    text-align: left;
                    vertical-align: top;
                    font-size: 0.95rem;
                }}
                .combo-overview-table thead th {{
                    background: #f5f7fa;
                    font-weight: 600;
                    color: #2c3e50;
                }}
                </style>
                """
                eval_details = selected_combo.get("eval_details") or []

                st.markdown("**指标评估明细**")
                if eval_details:
                    details_df = pd.DataFrame(eval_details)
                    if "score" in details_df.columns:
                        details_df["score"] = details_df["score"].apply(
                            lambda v: f"{v*100:.1f}%" if pd.notna(v) else "-"
                        )
                    for col in details_df.select_dtypes(include=[float, int]):
                        details_df[col] = details_df[col].map(_format_metric)
                    st.dataframe(details_df, width="stretch", hide_index=True)
                else:
                    st.info("该组合暂无评估明细。")

                st.markdown("**组合概览**")
                st.markdown(combo_table_html, unsafe_allow_html=True)
            else:
                st.info("新材料研发暂无结果。")
        elif st.session_state.step4_active:
            st.info("新材料研发尚未生成结果。")
        else:
            st.info("尚未启动新材料研发。")
