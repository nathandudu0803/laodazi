# 华为 PC 营销软文智能体

自研 Agent 闭环:场景解析 → 平台策略 → 知识库检索(事实与图片)→ 事实点提取 → 图文编排 → 软文生成 → 事实与图片核验 → 合规检查 → 导出。

知识库(ima)只提供华为产品事实和图片素材,软文由本项目的 Agent 生成。

## 快速开始

```bash
py -m pip install -r requirements.txt
cp .env.example .env   # 然后在 .env 填入自己的值,不要提交
```

环境变量见 `.env.example`。所有密钥只放环境变量,不写入源码、日志、截图。

## 检索实现

- `LocalRetriever`:读本地知识库副本(`LOCAL_KB_ROOT`),开发期使用。
- `ImaRetriever`:调用 ima 官方接口,提交前切换并跑全量测试。
- 两者实现同一个 `Retriever` 接口,上层代码不需要改。

## 协作

每人只改自己名下的文件,共享记录见 `docs/handoff.md`(只追加)。
