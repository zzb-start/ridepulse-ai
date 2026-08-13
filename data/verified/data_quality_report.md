# RidePulse AI 数据质量报告（冯敬琴）

> 数据版本：`DATASET-v1.0-feng-20260806`  
> 生成日期：2026-08-06  
> 阶段：开题/试点准备；不得将本文数字表述为生产效果。

## 结论

原始40条反馈已完成结构修复与来源门控：正式候选集37条，其中verified 16条、partially_verified 21条；另有3条因无法定位原文、403或非URL被隔离。原始文件未覆盖。

## 修复结果

- 反馈CSV：恢复12条被URL逗号拆开的记录。
- 来源台账：恢复5条标题/URL逗号造成的错位。
- 双人标注：移出尾部统计注释，修复F002与F011两条错位。
- 日期：月精度保留在`source_date_raw`，不伪造具体日。
- 截图：包内未提供截图目录，正式数据的`archive_path`全部留空，避免虚假路径。

## 质量门控

- 正式ID：`F0001`格式，映射见`id_mapping.csv`。
- 来源状态：正式集仅含`verified`与`partially_verified`。
- URL：正式集全部为HTTPS；无法定位的来源进入`rejected_records.csv`。
- 重复：按原文SHA-256检查，精确重复组0个（详见`duplicate_groups.csv`）。
- 局限：现有原始反馈仅40条，低于任务文档的50条盲标目标；现有双人标注仅20条，不能伪造额外李昂标签。

## 方法借鉴

本报告采用Google Data Cards式生命周期记录、W3C PROV式来源链，以及NIST AI RMF的测试/评测/验证记录原则。参考：

- https://research.google/pubs/data-cards-purposeful-and-transparent-dataset-documentation-for-responsible-ai/
- https://sites.research.google/datacardsplaybook/
- https://www.w3.org/TR/prov-o/
- https://airc.nist.gov/airmf-resources/airmf/5-sec-core/
