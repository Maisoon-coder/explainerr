# 一个通过本地规则+LLM辅助，帮我解释报错并给出下一步建议的 CLI 工具

`explainerr` 用中文解释终端报错：一句话结论、最多 3 条可能原因、最多 3 条下一步建议。

未启用模型配置时使用本地规则，无需 API key。运行时只依赖 Python 标准库，要求 Python 3.11+。所有建议命令仅打印，由你检查后决定是否执行。

下面是 Windows PowerShell 中的实际运行效果，展示直接传入报错和通过 stdin 读取报错两种用法。

![explainerr 运行截图：解释命令缺失和端口占用报错，并给出下一步检查建议](docs/images/cli-demo.png)

## 安装

在项目根目录执行：

```sh
python -m venv .venv
```

激活虚拟环境：

```sh
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

安装 CLI 和测试依赖：

```sh
python -m pip install -e ".[dev]"
```

仅使用 CLI 时可执行 `python -m pip install -e .`，不安装 pytest。未安装包时，在项目根目录也可直接使用 `python -m explainerr`。

如果 PowerShell 不允许激活脚本，可直接使用 `.\.venv\Scripts\python.exe` 和 `.\.venv\Scripts\explainerr.exe`。如果 `python` 指向不可用的 Windows 应用执行别名，请使用已安装的 Python 3.11+ 解释器的完整路径创建虚拟环境。

## 用法

```sh
explainerr "npm ERR! missing script: dev"
cat error.log | explainerr
explainerr --context "ModuleNotFoundError: No module named 'requests'"
python -m explainerr "bash: foo: command not found"
echo "EADDRINUSE: address already in use :::3000" | python -m explainerr
explainerr --help
explainerr --version
```

PowerShell 读取日志：

```powershell
Get-Content -Raw error.log | explainerr
```

报错以 `-` 开头时使用 `--` 分隔选项：

```sh
explainerr -- "--unexpected-option: command not found"
```

省略报错参数时从 stdin 读取，多行日志可以直接通过管道传入。参数和 stdin 同时存在时使用参数。报错输入超过 16000 字符会截断，并在 stderr 提示；空输入返回退出码 2。

## 输出示例

输入：

```sh
explainerr "npm ERR! missing script: dev"
```

输出：

```text
一句话结论：当前项目没有定义你要运行的 npm 脚本。
可能原因：
- package.json 的 scripts 中缺少该名称，或名称拼写不一致。
- 命令在错误的目录或工作区中执行。
下一步建议：
- npm run
- 检查 package.json 的 scripts 字段。
- 检查当前目录是否为目标项目根目录。
```

启用 `--context` 后，如果 `package.json` 的 `scripts` 可解析，还会列出其中已有的脚本名。端口占用规则在 Windows 建议 `netstat -ano`，在 macOS / Linux 建议使用 `lsof` 检查监听端口。

## 本地规则

| 报错类型 | 示例 |
| --- | --- |
| 命令缺失 | `command not found`、Windows 命令未识别 |
| 权限不足 | `Permission denied`、`EACCES`、`EPERM` |
| npm 脚本缺失 | `missing script: dev` |
| Python 模块缺失 | `ModuleNotFoundError: No module named 'requests'` |
| Python 名称导入失败 | `ImportError: cannot import name` |
| Node / 构建工具模块缺失 | `Cannot find module`、`ERR_MODULE_NOT_FOUND` |
| 端口占用 | `EADDRINUSE`、`Address already in use`、`WinError 10048` |

按具体类型优先匹配，整段日志输出一个解释。未命中的报错会明确说明无法确定原因，并给出通用检查项。本地规则不会猜测模块对应的安装包名，也不会推断所有项目的具体配置。

## 上下文与读取边界

默认不读取项目上下文。`--context` 仅从当前工作目录读取以下存在的文件：

- `package.json`
- `pyproject.toml`
- `requirements.txt`
- `README.md`

每个文件最多保留 4000 字符，四个文件合计最多 16000 字符；使用有界读取，不先加载整个文件。按 UTF-8 解码，非法字节替换为占位字符。缺失、无权限、非普通文件、符号链接、硬链接和 Windows 重解析点均跳过。不递归扫描，不读取 `.env`、密钥文件、`node_modules` 或 `.git`。

本地模式利用可解析的 `package.json` 补充 npm 脚本建议；其他白名单上下文用于可选 LLM 分析。截断导致 JSON 不完整时跳过脚本解析，仍输出本地解释。

## 模型配置存档（Profile）

Profile 将 API key、API 根地址和模型名保存为一个别名，方便在多个服务商之间切换。配置位于用户目录的 `~/.explainerr/config.json`，Windows 上对应 `%USERPROFILE%\.explainerr\config.json`，与项目目录无关。跨终端、跨项目目录使用时无需重新输入配置。

### 添加或更新配置

```sh
python -m explainerr profile add deepseek --api-key "替换为你的API密钥" --base-url https://api.deepseek.com --model deepseek-flash
```

使用相同别名再次执行会更新该配置，并保留其他配置和默认选择。别名支持中文、字母、数字、下划线、点和连字符，最长 64 个字符；首字符不能为点或连字符。密钥、地址和模型名不能包含空白或控制字符。管理命令只保存配置，不发送测试请求。

### 查看、使用和删除

```sh
# 查看已保存的别名、默认标记、base-url、model 和脱敏密钥
python -m explainerr profile list

# 指定本次使用的配置，不需要 EXPLAINERR_USE_LLM=1
python -m explainerr --profile deepseek "ModuleNotFoundError: No module named 'requests'"

# 也支持 stdin 和项目上下文
echo "EADDRINUSE: address already in use :::3000" | python -m explainerr --profile deepseek
python -m explainerr --profile deepseek --context "npm ERR! missing script: dev"

# 删除配置；如果它是默认配置，同时清除默认选择
python -m explainerr profile remove deepseek
```

`profile list` 中，长度超过 8 个字符的密钥只显示前 4 位和后 4 位，例如 `fake…5678`；短密钥全部显示为 `****`。

### 默认配置与选择顺序

```sh
python -m explainerr profile default deepseek
python -m explainerr "npm ERR! missing script: dev"
```

`profile default` 只能选择已保存的别名。设置后，不加 `--profile` 也会使用该配置调用模型。添加配置本身不会自动设为默认。

正常解释报错时，按以下顺序选择配置：

1. 命令行 `--profile <别名>` 指定的完整配置。
2. 环境变量：`EXPLAINERR_USE_LLM=1`，并且 API key 非空；URL 和模型名沿用下文的环境变量及默认值。
3. `~/.explainerr/config.json` 中的默认配置。
4. 都没有时，使用本地规则。

不同来源的密钥、地址和模型不会拼接成同一份配置。Profile 模式仍可通过 `EXPLAINERR_TIMEOUT` 调整超时。

要明确使用纯本地规则，即使已设置默认配置或环境变量，也可以执行：

```sh
python -m explainerr --local "bash: foo: command not found"
```

`--local` 与 `--profile` 不能同时使用。`EXPLAINERR_USE_LLM=0` 只关闭环境变量这一配置来源，不会取消已设置的默认 Profile；需要完全离线时使用 `--local`。

### 容错与密钥存储

指定别名不存在、配置文件损坏或不可读时，会显示明确提示并回退本地规则。显式指定的 Profile 不存在时，不会继续尝试环境变量或默认配置。已启用的环境变量优先于默认配置，因此不会受未使用的配置文件损坏影响。

模型请求失败时仍按原逻辑回退本地规则，失败详情和完整密钥不会打印。管理命令失败时返回退出码 2；解释报错成功（包括回退到本地）返回 0。损坏文件不会被 `profile add` 静默覆盖；请先移走用户目录中的损坏文件，再用 `profile add` 重新创建。

配置通过同目录临时文件写入后原子替换，避免写入中断清空旧配置。读取不会创建文件或目录，文件大小限制为 1 MiB。POSIX 系统中新建配置目录权限为 `0700`，配置文件为 `0600`；Windows 使用用户目录的访问权限。

API key 以明文保存在本机配置文件中，列表脱敏不等于加密。`--api-key` 参数也可能被终端历史或进程列表记录，请勿分享含真实密钥的命令、配置文件或截图。个人配置不属于项目文件；仓库同时忽略 `.explainerr/` 和根目录 `config.json`，不要将配置或备份复制进仓库。测试使用临时用户目录和假密钥，不读取真实配置或请求外部 API。

`profile` 是配置管理命令；如果要解释的报错文本恰好只有这个单词，可用 `python -m explainerr -- profile`。

## 可选 LLM 模式

除了保存 Profile，也可以使用环境变量临时配置模型。当 API key 非空且 `EXPLAINERR_USE_LLM=1` 时启用这一来源；它优先于默认 Profile，低于显式 `--profile`。没有可用配置时使用本地规则。

```sh
export OPENAI_API_KEY="你的 API key"
export EXPLAINERR_USE_LLM=1
explainerr --context "npm ERR! missing script: dev"
```

PowerShell：

```powershell
$env:OPENAI_API_KEY = "你的 API key"
$env:EXPLAINERR_USE_LLM = "1"
explainerr --context "npm ERR! missing script: dev"
```

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 未设置 | API 密钥；空值或仅空白不启用 LLM |
| `EXPLAINERR_USE_LLM` | 未设置 | 必须设为 `1` 才启用环境变量配置；不影响指定或默认 Profile |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 兼容服务的 API 根地址；自动追加 `/chat/completions` |
| `OPENAI_MODEL` | `gpt-4o-mini` | 服务提供的模型名；兼容服务应填写其支持的模型 |
| `EXPLAINERR_TIMEOUT` | `15` | 网络操作超时秒数，大于 0 且不超过 60；不是整个请求的严格总时限 |

同时兼容 `API_KEY`、`BASE_URL`、`MODEL` 简写。对应的两种名称同时设置时，`OPENAI_*` 优先；建议同一套环境配置统一使用一种命名。

通过标准库 `urllib` 发送 Chat Completions 请求，接口格式参考 [OpenAI API 文档](https://developers.openai.com/api/reference/resources/chat)。兼容地址例如 `https://your-provider.example/v1` 或本机服务 `http://localhost:8000/v1`；远程服务应使用 HTTPS。API 根地址不能带用户名、密码、查询参数或 URL 片段；不接受重定向。

请求只包含模型名和消息，不要求服务支持 JSON schema 参数。服务需要返回 JSON 解释，程序在本地校验字段、条目数量和中文结论/原因，并统一为固定格式。建议中的命令可包含英文命令名。

超时、网络错误、HTTP 错误、错误配置、超大响应、非 JSON 响应或不合格输出都会自动回退到本地规则。失败提示写入 stderr，不打印异常详情、API key 或响应正文；stdout 保持三段格式，解释成功退出码为 0。中断退出码为 130。

启用 LLM 时，报错文本会发送给配置的 API 服务；同时使用 `--context` 时，截断后的白名单文件内容也会发送。程序不自动脱敏这些文本，传入前应检查其中是否包含密钥。本地模式无需网络。程序不加载 `.env`，环境变量需要由终端或调用方设置。

### 切换到其他模型服务

`explainerr` 已在 `llm.py` 中通过标准库 `urllib` 实现 OpenAI 兼容接口调用。切换服务商时，直接设置环境变量即可，无需修改代码或安装 `openai` SDK。

需要配置以下四项：

1. `OPENAI_API_KEY`：目标服务商提供的 API key。
2. `OPENAI_BASE_URL`：该服务商的 OpenAI 兼容 API 根地址。
3. `OPENAI_MODEL`：该服务商支持、且你的账户有权调用的模型名。
4. `EXPLAINERR_USE_LLM=1`：启用 LLM 模式。

无论使用哪家服务，变量名都保持为 `OPENAI_API_KEY`，只替换它的值。例如接入 DeepSeek 时，这里填写 DeepSeek 的密钥。程序不会自动读取 `DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY` 或 `DASHSCOPE_API_KEY`，也不要把密钥写进 `llm.py`。

以下配置示例于 **2026-11-16** 根据官方文档核对，未逐家进行真实 API 调用。模型名、地域地址和账户权限可能变化，使用时以对应平台控制台及文档为准。

| 服务商 | `OPENAI_BASE_URL` | `OPENAI_MODEL` 示例 | 官方文档 |
| --- | --- | --- | --- |
| DeepSeek | `https://api.deepseek.com` | `deepseek-flash` | [首次 API 调用](https://api-docs.deepseek.com/) |
| Kimi（月之暗面） | `https://api.moonshot.cn/v1` | `kimi-k3.1-pro` | [快速开始](https://platform.kimi.com/docs/get-api-key) |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3` | [OpenAI API 兼容](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction) |
| 通义千问（阿里云百炼，北京地域） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | [模型调用示例](https://help.aliyun.com/en/model-studio/model-calling-in-sub-workspace) |
| MiniMax（国内平台） | `https://api.minimax.cn/v1` | `MiniMax-M3.1-Flash` | [OpenAI 兼容接口](https://platform.minimax.cn/docs/api-reference/text-openai-api) |

`OPENAI_BASE_URL` 填写表中的根地址即可，程序会自动追加 `/chat/completions`。API key、地址和模型名需要对应同一家服务及其适用地域；如果控制台提供工作空间专属地址，使用该地址。

#### 示例：接入 DeepSeek

在运行 `explainerr` 的同一个终端中设置变量。将占位文字替换为你自己的 API key。

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY = "你的 DeepSeek API key"
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:OPENAI_MODEL = "deepseek-flash"
$env:EXPLAINERR_USE_LLM = "1"

python -m explainerr "npm ERR! missing script: dev"
```

macOS / Linux：

```sh
export OPENAI_API_KEY="你的 DeepSeek API key"
export OPENAI_BASE_URL="https://api.deepseek.com"
export OPENAI_MODEL="deepseek-flash"
export EXPLAINERR_USE_LLM=1

python -m explainerr "npm ERR! missing script: dev"
```

如果已设置服务商自己的密钥变量，可以将其值赋给程序读取的变量，例如 PowerShell 中使用 `$env:OPENAI_API_KEY = $env:DEEPSEEK_API_KEY`，或在 macOS / Linux 中使用 `export OPENAI_API_KEY="$DEEPSEEK_API_KEY"`。

改用其他服务时，替换上述示例中的密钥、根地址和模型名即可。配置默认只对当前终端及其启动的进程生效。

#### 检查配置与切回本地模式

如果看到“LLM 调用失败，已回退到本地规则模式”，依次检查 API key 是否有效、地址是否重复包含 `/chat/completions`、模型是否可用，以及账户额度和网络连接。仍然输出解释不代表 API 调用成功，因为本地规则会自动接管。

响应较慢时，可将 `EXPLAINERR_TIMEOUT` 调整为 `60`；超过超时或响应大小限制仍会回退。当前客户端仅发送 `model` 和 `messages`，服务返回的 `choices[0].message.content` 需要包含符合要求的 JSON 解释。必须额外传入专属参数的服务，需要先扩展客户端，不能仅靠这些环境变量配置。

需要恢复本地规则模式时，执行 `python -m explainerr --local "报错文本"`。如果没有默认 Profile，也可以在 PowerShell 中设置 `$env:EXPLAINERR_USE_LLM = "0"`，或在 macOS / Linux 中设置 `export EXPLAINERR_USE_LLM=0`；其他配置可以保留。

## 验证

安装开发依赖并激活虚拟环境后执行：

```sh
python -m explainerr "bash: foo: command not found"
echo "EADDRINUSE: address already in use :::3000" | python -m explainerr
python -m explainerr --context "ModuleNotFoundError: No module named 'requests'"
pytest
```

也可以使用 `python -m pytest`。测试使用临时用户目录、假密钥和模拟 HTTP 响应，不需要真实 API key，也不访问外部 API。覆盖原有规则、CLI、上下文和 LLM 回退，以及 Profile 增删改、默认选择、配置优先级、密钥脱敏、损坏文件、读写权限错误和原子写入失败保护。

## 项目结构

```text
explainerr/
  __init__.py       版本
  __main__.py       python -m explainerr 入口
  cli.py            参数、stdin、模式选择
  models.py         输出约束和渲染
  rules.py          本地规则
  context.py        受限上下文读取
  llm.py            可选兼容 API 客户端
  profiles.py       用户目录配置存档与优先级选择
tests/              pytest 测试
pyproject.toml      打包、CLI 命令和开发依赖
```

MVP 不包含网页、数据库、shell hook、插件系统、自动执行修复命令或自动改写项目文件。输出语言仅中文。
