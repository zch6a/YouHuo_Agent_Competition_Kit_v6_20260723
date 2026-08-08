# 优活 Agent v6 研究与工程依据

## 1. 竞赛与鸿蒙依据

- 2026 C4-AI官方主页：鸿蒙高校创新赛与昇腾AI创新大赛，面向高校学生，最多3人组队。  
  https://developer.huawei.com/home/C4-AI
- 鸿蒙高校创新赛页面：强调自由创作、前沿创新、实用落地、全场景智能设备和多设备联动。  
  https://developer.huawei.com/consumer/cn/activity/incentive/C4
- HarmonyOS 7开放Skill、Agent、云A2A与端A2A，支持Agent一次开发、多端交互。  
  https://developer.huawei.com/consumer/cn/information/news/76a6999fe8a74a05a2156f9d38e301e0

工程落地：`harmonyos/`、`xiaoyi/`、`plugin_openapi_v6.generated.json`、`FinalistWalkthroughPage.ets`。

## 2. 往届获奖作品给出的启示

公开的一等奖与优秀项目通常具有共同特点：

1. 面向清晰、可理解的真实痛点；
2. 有可演示的技术核心，而非只写商业计划；
3. 能量化说明技术改善了什么；
4. 场景聚焦，五分钟内能看懂；
5. 有产品形态、用户证据或应用单位证据。

2025年公开报道中的项目覆盖视障导航、脑控轮椅、医疗健康、工业检测等明确场景。优活因此不以“养老功能数量”竞争，而聚焦“老人如何安全、低负担地完成数字事务”。

## 3. 老年人语音交互研究

### 3.1 语音能降低部分操作负担，但不能假设人人都会用

2026年的共创研究发现，语音输入可以降低认知负担，但80岁以上用户仍可能遇到明显可用性困难；透明的“Glass Box”教育与提示有助于从盲信转向基于证据的信任。

- Chen et al., *Bridging the Cognitive Gap: Co-Designing and Evaluating a Voice-Enabled Community Chatbot for Older Adults*, 2026.  
  https://arxiv.org/abs/2603.11303

工程落地：`CognitiveLoadGovernor`、`RelianceCardService`、重复播报、字号/语速与选项上限。

### 3.2 ASR对认知障碍和非典型语音存在公平性缺口

2026年研究报告了认知障碍老年人的ASR错误率上升，并建议个性化ASR、人机校正和交互级适应。

- Cohn et al., *Challenges in Automatic Speech Recognition for Adults with Cognitive Impairment*, 2026.  
  https://arxiv.org/abs/2602.23436

工程落地：N-best语音共识、低置信度澄清、`VoiceBench-v6`和交互档案。当前Benchmark仍是合成转写，真实音频评估是明确缺口。

### 3.3 隐私、文化、信任和自主权决定是否愿意使用

- LaRubbio et al., *Navigating Privacy and Trust: AI Assistants as Social Support for Older Adults*, 2025.  
  https://arxiv.org/abs/2505.02975
- Green et al., *Black Older Adults' Perception of Using Voice Assistants to Enact a Medical Recovery Curriculum*, 2025.  
  https://arxiv.org/abs/2503.11894

工程落地：老人同意优先记忆、家属最小摘要、陪聊原文不共享、数据权利中心、方言提示和家属接力而非替代老人。

## 4. Agent工程与安全依据

### 4.1 有状态工作流与Human-in-the-loop

LangGraph等工程强调持久状态、人工介入、恢复和可控流程。优活使用自研确定性状态机和Saga，避免比赛离线环境依赖过重框架。

- https://github.com/langchain-ai/langgraph

### 4.2 最终状态评测

τ-bench强调不能只看模型回答“成功”，必须检查环境最终状态。优活采用权威数据库状态、回执、审批快照和证明包判断完成。

- https://arxiv.org/abs/2406.12045

### 4.3 工具型Agent攻击

AgentDojo等工作表明，工具返回、网页和文档可携带提示注入。优活把OCR/VLM/网页内容视为不可信数据，并通过目的绑定和字段白名单约束。

- https://arxiv.org/abs/2406.13352

### 4.4 Policy-as-code和数据/控制分离

OPA体现策略从业务逻辑分离；CaMeL路线强调可信控制流和不可信数据流分离。优活的`PurposeBoundPolicy`位于模型之外，模型不能修改权限。

- https://github.com/open-policy-agent/opa

## 5. v6相较v5的研究增量

1. 从“有语音”推进到“语音不确定性治理”；
2. 从“大字版”推进到“认知负荷自适应”；
3. 从“安全策略后台运行”推进到“老人可理解的玻璃盒卡片”；
4. 从“文档不可信”推进到“可信与不可信值冲突必须澄清”；
5. 从“有Benchmark”推进到“区分真实用户、合成语音文本和软件性质测试”；
6. 从“鸿蒙工程壳”推进到明确的Core Speech、Push、分布式档案和端A2A适配接口。
