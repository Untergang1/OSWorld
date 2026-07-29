# OSWorld 科研专业软件场景适配工作报告

## 1. 项目概述

本项目以开源桌面自动化基准 **OSWorld** 为基础，面向科研专业软件的图形界面操作与结果验证需求进行了适配。原始基准主要覆盖办公、浏览器等通用桌面应用；本次工作将可评测范围扩展到四类典型科研软件场景：红外光谱（OMNIC）、X 射线光电子能谱（Avantage）、原子力显微镜（NanoScope Analysis）和透射电子显微镜/电子能量损失谱（GMS/DigitalMicrograph）。

适配工作包括四个互相衔接的部分：构建包含四套软件的可复位 Windows 虚拟机；设计任务、输入数据与自动检验函数；接入 UIAgent 的执行和结果采集能力；以及基于 OSWorld 虚拟机服务采集 UI-TARS-LoRA 所需的视觉界面训练数据。这样既可以对智能体完成专业软件操作的能力进行评测，也能够沉淀可用于后续模型训练的界面理解数据。

当前任务配置位于 `evaluation_examples/examples_windows`：四个软件域各包含 5 个任务，共 20 个任务；集合入口为 `evaluation_examples/test_scikit_windows.json`。

| 软件场景 | 科研对象 | 当前任务数 | 代表性操作 |
| --- | --- | ---: | --- |
| OMNIC | FTIR/ATR 红外光谱 | 5 | 指纹区导出、基线校正、峰提取、谱库匹配、报告导出 |
| Avantage | XPS 能谱 | 5 | C 1s 拟合、多区域定量、荷电校正、结果表和谱图导出 |
| NanoScope Analysis | AFM 高度图与力曲线 | 5 | 粗糙度、截面、平整化、颗粒分析、力曲线基线处理 |
| GMS/DigitalMicrograph | TEM 图像和 EELS 谱 | 5 | 晶格标定、FFT/衍射测量、元素图、EELS 背景扣除 |

## 2. Windows 虚拟机部署与快照构建

### 2.1 环境准备

1. 在 VMware 中创建 Windows 虚拟机，并为虚拟磁盘预留**至少 60 GB**空间，以容纳操作系统、四套专业软件、运行缓存和任务导出文件。
2. 启动 Windows 后，打开“控制面板 - 程序和功能 - 启用或关闭 Windows 功能”，勾选并安装 **.NET Framework 3.5**。该组件应在安装专业软件前完成配置。
3. 将 OMNIC、Avantage、NanoScope Analysis 和 GMS/DigitalMicrograph 的安装包逐一复制到虚拟机中，按各软件安装向导完成安装。安装过程使用合法授权的软件包；授权文件、序列号和账号信息不写入代码仓库或任务配置。
4. 分别启动四个软件，确认主窗口能够正常打开。当前任务配置使用的可执行文件路径和窗口名如下；若实际安装路径不同，应先调整相应任务 JSON 的 `config` 配置。

| 软件 | 可执行文件 | 等待的窗口名 |
| --- | --- | --- |
| OMNIC | `C:\Program Files (x86)\Omnic\omnic32.exe` | `OMNIC` |
| Avantage | `C:\Program Files (x86)\Thermo\Avantage\Bin\Avantage.exe` | `Avantage` |
| NanoScope Analysis | `C:\Program Files\Bruker\NanoScopeAnalysis\NanoScopeAnalysis.exe` | `NanoScope` |
| GMS/DigitalMicrograph | `C:\Program Files\Gatan\DigitalMicrograph.exe` | `DigitalMicrograph` |

### 2.2 固化基线状态

软件均可用后，关闭安装程序和不必要的临时窗口，在 VMware 管理面板中为该虚拟机创建快照，名称为 **`SciKit_ready`**。该快照表示“基础系统和四套应用已就绪、但未预置某个具体任务数据”的干净初始状态。

每一个科研软件任务的 JSON 都在根字段中设置：

```json
"snapshot": "SciKit_ready"
```

OSWorld 在任务开始时恢复该快照，再按任务配置布置输入文件和启动软件。这种设计将环境构建与任务数据解耦：快照保持稳定，任务之间不会互相污染，任务所需数据也无需提前保存到快照中。

## 3. 任务、数据与自动检验

### 3.1 任务组织与执行流程

每个任务均以独立 JSON 文件保存，包含唯一 `id`、自然语言 `instruction`、来源 `source`、初始化 `config`、相关软件 `related_apps` 和 `evaluator`。典型初始化序列为：

1. `upload_file`：将仓库本地的输入文件上传到虚拟机 `C:\Users\User`；
2. `execute`：创建输出目录、清理同名历史结果；Avantage 任务还会将输入 ZIP 解压到该目录；
3. `open`：通过绝对路径启动目标软件并等待目标窗口出现；
4. `sleep`：等待应用完成初始化后再交由智能体操作。

输入资产位于 `evaluation_examples/scikit_assets/<软件名>`。任务运行时只上传当前任务需要的文件；智能体完成操作后，也将 CSV、TXT、PDF 或图像结果保存到 `C:\Users\User`。这避免了将所有原始数据预复制进快照，并使每个任务的输入、输出和初始化动作可审计、可复现。

其中，OMNIC 的 `unknown_clear_coating.jdx` 和谱库 CSV、NanoScope 的合成高度图/力曲线、GMS 的合成 TEM/EELS 输入均为确定性 benchmark 数据；Avantage 任务使用由 CasaXPS 示例整理得到的 XPS 项目输入。它们用于检验软件操作流程，不应被表述为真实实验测量数据。

### 3.2 自动评测设计

评测函数位于 `desktop_env/evaluators/metrics/scikit.py` 与 `desktop_env/evaluators/metrics/omnic.py`。评测器先从虚拟机取回 `evaluator.result` 指定的文件，再依据任务规则进行分层检查：

- 对所有输出检查文件存在性、扩展名与最小字节数；
- 对 CSV 检查表头关键词、数值行/列数、数值范围与关键峰位或能量值的容差；
- 对文本和 PDF 检查必需术语，PDF 进一步提取文本验证；
- 对图像检查尺寸、颜色特征或 FFT 中心亮度等结构特征；
- 对多数任务设置输入或模板文件的 `forbidden_sha256`，防止智能体直接复制输入文件伪造结果。

例如，OMNIC 峰表任务会检查特征峰位置和导出表格的数值行数；Avantage 任务会检查 C 1s、O 1s 等定量结果的关键字段；NanoScope 任务要求报告中包含 `Ra` 与 `Rq`，或验证截面/力曲线覆盖范围；GMS 的 EELS 任务检查 C-K 和 O-K 能量位置，FFT 和元素图任务检查导出图像的有效性。由此，评测目标从“是否生成文件”提升为“是否产生包含目标科学信息的结果”。

## 4. UIAgent 适配与运行

### 4.1 适配方式

`scripts/python/uiagent/run_task.py` 提供 UIAgent 与 OSWorld 的单任务桥接。脚本读取任务 JSON，按其 `snapshot` 恢复 Windows 环境，创建 OSWorld `DesktopEnv`，并将 VM 服务地址、操作系统类型、任务配置等信息传递给 UIAgent 的 `osworld_windows` 后端。UIAgent 通过 `pyautogui` 动作空间完成桌面操作，OSWorld 继续负责环境重置、文件上传、软件启动和最终 evaluator 调用。

运行前应提供可用的 UIAgent 源码根目录（其中包含 `services/execution_service.py` 与 `backend/osworld_windows`），或已按其要求完成 editable 安装和模型服务配置。模型端点、API 密钥等运行时配置只通过本地环境传入，不记录在任务或结果文件中。

单任务示例：

```powershell
python scripts/python/uiagent/run_task.py `
  --uiagent-root <UIAgent根目录> `
  --vmx <Windows虚拟机.vmx> `
  --task-config evaluation_examples/examples_windows/omnic/<任务ID>.json `
  --max-steps <最大步数>
```

`scripts/python/uiagent/eval_windows.py` 提供单虚拟机批量执行和 OSWorld 自动评分入口。例如可使用 `--meta evaluation_examples/test_scikit_windows.json --domain all` 选择全部科研软件任务；实际运行时一次只应向同一虚拟机分配一个执行环境。

```powershell
python scripts/python/uiagent/eval_windows.py `
  --uiagent-root <UIAgent根目录> `
  --vmx <Windows虚拟机.vmx> `
  --meta evaluation_examples/test_scikit_windows.json `
  --domain all `
  --result-dir results/uiagent_scikit
```

对于多个可独立分配的虚拟机，可使用 `scripts/python/uiagent/run_multienv_uiagent.py`。该脚本通过多进程队列为每个环境创建一个 `DesktopEnv`；在 VMware/VirtualBox 模式下，`--num_envs > 1` 时不应将多个进程绑定到同一 `--path_to_vm`，而应由 OSWorld 分配可用虚拟机。

### 4.2 结果与轨迹归档

批量运行会在结果目录中保存每个任务的任务配置、指令、UIAgent 执行记录、评分结果和错误信息，并在汇总文件中记录任务状态。多环境脚本还可以同步 UIAgent 原始日志，提取执行过程中的起始截图、步骤后截图及动作/决策记录，形成可回放的 `traj.jsonl`。这些产物支持错误分析、人工复核和后续训练样本筛选。

## 5. 面向 UI-TARS-LoRA 的训练数据构建

### 5.1 截图和 UIA 采集

`train_data/capture_uia.py` 复用 OSWorld 虚拟机服务，在同一时刻请求 `/screenshot` 和 `/accessibility` 接口。调用形式如下：

```powershell
python train_data/capture_uia.py --vm-ip <虚拟机IP> --app-name avantage
```

脚本保存四类可追溯产物到 `train_data/captures/<app>/<时间戳>/`：

- `raw_screenshot.png`：未经标注的原始屏幕截图；
- `raw_accessibility.xml`：虚拟机返回的原始 UI Automation 树；
- `filtered_uia.json`：与截图坐标对齐后的活动窗口元素；
- `annotated_screenshot.png`：用于人工检查元素框的标注图。

采集过程解析 UIA 元素的控件类型、名称/内容、状态、父子关系与屏幕矩形；根据全屏根元素推断 DPI 坐标变换，将 UIA 坐标投影到截图像素坐标。随后依据键盘焦点、焦点元素、模态窗口和最大化非桌面窗口识别当前活动窗口，仅保留活动窗口及其可见覆盖层，排除桌面、任务栏和非活动应用元素。这样生成的元素框能够同时服务于视觉 grounding 标注和后续交互定位。

### 5.2 元素描述与数据集组织

`train_data/generate_avantage_v3.py` 以已有的元素框和原始截图为输入，先用截图 SHA-256 与 UIA 矩形进行一一匹配，再按同一截图分批请求兼容 OpenAI 接口的多模态模型生成英文元素描述。每一批输入包含未画框的完整截图、目标框坐标和局部上下文裁剪图；UIA 仅向模型提供该元素的 `content` 作为辅助，描述以视觉证据为主，避免把不可见的 UIA 元数据直接写入训练文本。

生成器对模型输出执行 JSON、语言、长度和一目标一描述校验，以 JSONL 检查点逐条持久化进度，支持失败重试与断点续跑；全部完成后原子写出 `annotations.csv` 并复制原始图像。最终标注 CSV 的字段为：

```text
id,image,description,left,top,right,bottom,app_version
```

其中坐标使用截图像素，`left/top` 为包含边界，`right/bottom` 为排除边界。`train_data/label_annotations.py` 可基于该 CSV 生成带框质检图，以检查描述与元素位置是否一致。

当前训练数据以 Avantage 场景的完整标注示例为主：`train_data/avantage/v4/annotations.csv` 现有 324 条描述、146 个唯一元素框；OMNIC 已有截图与 UIA 采集样本。该状态说明训练数据管线已经建立，但不将其表述为四个软件场景均已完成同等规模的 LoRA 标注集。旧版概览文档与当前 CSV 的统计存在差异时，应以当前 CSV 的实测内容为准。

## 6. 可复现性与使用边界

本适配方案通过“稳定软件快照 + 任务时上传输入资产 + 结构化自动评测”的方式控制实验初态；通过 UIAgent 日志、评分文件、截图和 UIA 原始数据保留执行证据；通过不保存密钥、许可证和真实虚拟机信息降低敏感配置泄露风险。

实际运行真实虚拟机、专业软件或外部模型服务时，仍需在具备相应软件授权、VMware 配置和本地模型/网络环境的机器上执行。本文说明的是仓库中已实现的构建和操作方法，不以未实际运行的任务得分替代实验结果。

