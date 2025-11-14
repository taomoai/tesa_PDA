# app 模块学习笔记

## 整体概览
- `app/input_reverser.py`、`app/approximate_search.py`、`app/search.py` 围绕胶带产品的属性检索与推荐展开，核心数据来源于 `data/*.csv` 与 `models/*.joblib`。
- 算法主轴包括基于 Sklearn 的线性回归预测、OR-Tools 混合整数规划求解、笛卡尔积穷举与差异度量、PCA 降维与核密度估计、带容差的区间过滤与匹配评分。
- 三个文件在职责上分层：`search.py` 提供精确过滤，`approximate_search.py` 面向模糊匹配与可视化，`input_reverser.py` 实现从目标性能反推材料组合的逆向设计。

## `app/input_reverser.py` —— 逆向设计与优化求解
- **模型加载与标准化**：通过 `joblib` 动态载入以 `Item_No` 命名的线性回归模型，并还原 `StandardScaler` 均值与方差，用于预测开放/覆盖面剥离力及总厚度。
- **特征空间构建**：依据材料库中可用的基材厚度、胶粘剂剥离力、双面涂布量，采样或笛卡尔积生成组合特征矩阵。
- **预测与评分机制**：对每个组合调用模型预测，在硬性约束（厚度不可低于目标）基础上按三个指标计算平均差异比，并映射为 0~1 分值以排序最佳方案。
- **OR-Tools 求解器**：`solve_material_choice` 使用 SCIP 后端构造整数变量（材料选择）与连续变量（惩罚项），目标函数最小化厚度与剥离力偏差，实现混合整数规划求解。
- **NART 反查**：在得到预测特征后，利用 `_find_backing_nart` 和 `_find_adhesive_nart` 在材料属性表中检索具体物料编号，实现性能到物料的映射。
- **Pydantic 数据结构**：`ProductPredictedProperty`、`ProductEvalDetail` 等模型确保预测结果、评分细节和说明文案结构化输出，便于前端消费。

## `app/approximate_search.py` —— 模糊匹配与可视化分析
- **多表加载与映射**：同步读入产品、扩展属性、各类材料属性与 `Item_No` 映射，为跨表信息整合提供基础。
- **带容差的属性筛选**：`_filter_by_property_range` 支持上下界缺省、按比例放宽范围（`tolerance_ratio`），对属性缺失的产品自动放行，适应真实数据稀疏性。
- **属性匹配评分**：`_calculate_match_score` 将属性偏差映射成 0~100 分，平均后形成 `match_score`，用于结果排序与雷达图展示。
- **雷达图生成**：`draw_match_radar` 使用 Matplotlib 极坐标可视化多维匹配度，输出 Base64 编码便于嵌入前端。
- **PCA + KDE 分析**：`draw_product_PCA` 对关键数值属性做标准化与主成分分析降维，再用 `scipy.stats.gaussian_kde` 估算密度绘制等高线，并根据目标指标上色，直观展示产品分布。
- **产品列表构建**：`_build_product_list` 联合扩展表与原始属性表重建 `Product`（含 NART 与属性详情），`approximate_product_search` 返回产品清单与雷达图两类结果。

## `app/search.py` —— 精确过滤与结构化封装
- **快速查找实现**：`ProductSearch.search_products` 以 `df_product_extended` 为基准，逐项应用精确或带极小容差的过滤条件（厚度、颜色、剥离力、移除力、标签等），适用于目标区间明确的场景。
- **属性封装**：将结果整合为 `Product`（含 NART、标签、`Property` 列表），每个 `Property` 包含名称、上下界、原始值、测试方法等信息，方便前端展示。
- **数据复用**：与 `approximate_search` 共用数据结构和映射逻辑，确保精确搜索与模糊搜索的一致性。

## 学习与实践建议
- 熟悉 `data/` 目录下 CSV 结构和 `models/` 模型，理解特征命名及单位。
- 在 `input_reverser` 中尝试调整特征上下界或步长，观察组合规模、运行时间对预测精度的影响；亦可探索替换/扩展回归模型（如 XGBoost）。
- 对 OR-Tools 求解部分，可添加更多业务约束或权重配置，比较多目标优化表现。
- `approximate_search` 的容差调节、评分函数与可视化流程是模糊推荐的范例，可进一步引入聚类或交互式展示。
- `search` 提供清晰的条件过滤模板，便于扩展新的搜索字段或优化矩阵运算。


