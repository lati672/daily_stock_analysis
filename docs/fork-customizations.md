# 本 Fork 的自定义功能与 Upstream 同步说明

本文记录 `lati672/daily_stock_analysis` 相对上游
`ZhuLinsen/daily_stock_analysis` 保留的本地扩展，供日常使用、环境重建和后续同步
upstream 时核对。它不替代项目的完整指南或更新日志：

- 功能和配置细节仍以 [完整配置与部署指南](full-guide.md) 为准；
- 每次具体变更仍记录在 [更新日志](CHANGELOG.md)；
- 本文重点回答“这个 fork 额外提供什么”和“同步 upstream 时要保护什么”。

## Git 远端关系

当前约定：

| Remote | 仓库 | 用途 |
| --- | --- | --- |
| `origin` | `https://github.com/lati672/daily_stock_analysis.git` | 本 fork，保存自定义功能 |
| `upstream` | `https://github.com/ZhuLinsen/daily_stock_analysis.git` | 官方上游，只用于获取更新 |

检查远端：

```bash
git remote -v
```

## 自定义功能

### 1. Moomoo 只读账户看板

WebUI 增加 `/account` 页面，通过后端连接已登录的 Moomoo OpenD：

- 分别展示美股与港股持仓；
- 展示总市值、持仓盈亏、今日盈亏和持仓明细；
- 使用 OpenD 的 `average_cost` 作为平均成本；
- 展示今日涨幅、仓位、持仓盈亏、未实现盈亏和已实现盈亏；
- 所有持仓字段支持“降序 → 升序 → 默认排序”的三段排序；
- 港股价格和盈亏使用 HKD，美股使用 USD；账户顶部混合币种汇总先折算为 USD；
- 账户资产按原币展示 AUD、USD、HKD 现金余额、可提金额和现金购买力，不跨币种直接混加；
- 支持手动刷新持仓和行情快照。

安全边界：此页面只调用账户、持仓和行情查询接口，不收集登录密码或交易解锁密码，
也不提供下单、改单、撤单或解锁交易能力。

主要维护位置：

| 层级 | 文件 |
| --- | --- |
| Web 页面 | `apps/dsa-web/src/pages/AccountPage.tsx` |
| Web API 与类型 | `apps/dsa-web/src/api/moomoo.ts`、`apps/dsa-web/src/types/moomoo.ts` |
| API 入口与 Schema | `api/v1/endpoints/portfolio.py`、`api/v1/schemas/portfolio.py` |
| OpenD 适配 | `src/brokers/futu/portfolio.py` |

### 2. Moomoo 持仓与 AI 问股联动

- 从单项持仓点击“AI 分析”时新建独立对话，并带入对应证券上下文；
- 从账户概览点击“AI 归因”时新建独立对话，分析今日盈亏贡献；
- 问股页提供“结合我的 Moomoo 持仓”开关，默认关闭；
- 服务端先确定性计算市场内仓位、今日盈亏贡献和贡献排序，再交给 LLM 解释；
- 发送给模型的上下文不包含账户 ID、OpenD 地址或交易能力；
- 单股问答默认不刷新无关市场的全部持仓行情，减少等待 OpenD 港股接口的时间。

主要维护位置：

- `apps/dsa-web/src/pages/ChatPage.tsx`
- `apps/dsa-web/src/stores/agentChatStore.ts`
- `api/v1/endpoints/agent.py`
- `src/services/moomoo_ai_context.py`
- `src/agent/tools/data_tools.py`

### 3. AI 回复的 Discord 单条发送

- 问股页可自动将新生成的 AI 回复发送到 Discord；
- 每条 AI 回复下方提供独立 Discord 发送按钮；
- 单条发送不会附带完整历史对话，也不会投递到其他通知渠道；
- 自动发送开关保存在当前浏览器，默认关闭；
- 复用项目现有 Discord Webhook/Bot 配置、分片、限流重试和日志脱敏逻辑。

主要维护位置：

- `apps/dsa-web/src/pages/ChatPage.tsx`
- `apps/dsa-web/src/api/agent.ts`
- `api/v1/endpoints/agent.py`
- `src/notification_sender/discord_sender.py`

### 4. 问股交互与模型兼容调整

- AI 回复的复制、导出和 Discord 操作位于回复正文下方；
- 消息滚动区域与顶部边框之间保留留白；
- 经 Chat Completions 调用不兼容“工具 + reasoning effort”组合的模型时，工具调用路径将
  `reasoning_effort` 设置为 `none`，纯文本调用保持原配置。

### 5. WebUI 进程退出改进

`python main.py --webui-only` 和 `--serve` 会处理 `SIGINT` / `SIGTERM`，等待后台
Uvicorn 退出并释放端口，减少按下 `Ctrl+C` 后仍需手动清理 8000 端口的情况。

### 6. 收盘后自动持仓日报

账户页提供服务端持久化的“自动持仓日报”开关。启用后，WebUI/API/Desktop 长运行进程会在
`MOOMOO_DAILY_REPORT_TIME` 指定的服务器本地时间执行：

1. 从已登录 OpenD 读取只读实时持仓；
2. 由程序计算各市场盈亏归因、主要正负贡献和证券集中度；
3. 让 Agent 针对主要贡献者或集中持仓查询新闻并整理下一交易日关注点；
4. 将完成的 Markdown 日报仅发送到 Discord。

该调度独立于普通 `SCHEDULE_ENABLED` 分析任务。账户页也提供“立即生成并发送”按钮用于
测试；生成中的任务不会并发重复启动。调度器按纽约本地日期判断美股交易日，美股周末及
NYSE 节假日自动跳过并将下次运行推进到下一交易日，但不会关闭持久开关；手动按钮仍可覆盖。
日报对话会保留在问股历史中，便于审计模型输出。

## 配置与外部服务

不要把真实密钥、账户 ID 或交易密码写进本文或提交到 Git。配置应写入本地 `.env`，
字段模板以 `.env.example` 为准。

### Moomoo OpenD

```dotenv
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_SECURITY_FIRM=NONE
# FUTU_ACC_ID=
MOOMOO_DAILY_REPORT_ENABLED=false
MOOMOO_DAILY_REPORT_TIME=18:10
```

使用前需要在本机启动并登录 OpenD。当前集成使用 IPv4；在 Docker 中连接宿主机 OpenD
时不能使用容器自身的 `127.0.0.1`。

`MOOMOO_DAILY_REPORT_TIME` 使用服务器本地时区。若同时持有美股和港股，应把它设置为最后
一个目标市场收盘之后的时间。启用日报还需要有效的 LLM、新闻搜索和 Discord 配置。

### Discord

选择 Webhook，或选择 Bot Token 与频道 ID：

```dotenv
# 方式一
DISCORD_WEBHOOK_URL=

# 方式二
DISCORD_BOT_TOKEN=
DISCORD_MAIN_CHANNEL_ID=
```

## 依赖边界

### Python 运行时依赖

本 fork 的 Moomoo 能力直接依赖：

```text
futu-api==10.9.6908
```

该依赖已写入根目录 `requirements.txt`。代码会优先兼容单独安装的 `moomoo-api`，并回退
到项目锁定的 `futu-api`；标准环境只需安装 `requirements.txt`，不需要同时安装两个 SDK。

其他自定义后端代码只使用 Python 标准库或已经存在的直接依赖，例如 `fastapi` 和
`requests`。Discord 单条发送复用现有通知实现，不需要新增 Discord 运行时库。

### 前端依赖

账户页、问股联动和 Discord 开关均复用现有 React、状态管理、图标和 API 客户端，
没有引入额外 npm 包。前端依赖仍以 `apps/dsa-web/package.json` 和 lockfile 为准。

### 开发与测试依赖

`pytest`、`flake8` 和 `pytest-timeout` 属于开发/CI 工具，已由
`.github/requirements-ci.txt` 管理，不应加入生产运行时 `requirements.txt`。
Moomoo OpenD 是独立的本地应用，也不是 Python 包依赖。

## 同步 Upstream

建议始终在独立分支尝试同步，不直接在主分支上解决未知冲突：

```bash
git status --short --branch
git fetch --all --prune
git switch -c codex/sync-upstream-vX.Y
git merge upstream/main
```

存在未提交修改时，不要强行切分支、stash、reset 或覆盖工作树；先提交当前功能，或明确
决定如何保存这些修改。

### 高冲突风险区域

同步后重点检查：

1. `api/v1/endpoints/agent.py` 与 `portfolio.py` 的路由是否仍注册且响应 Schema 兼容；
2. `ChatPage.tsx` 的 upstream 对话状态更新是否覆盖了新建会话、持仓开关或 Discord 发送；
3. `AccountPage.tsx` 使用的持仓字段是否仍与后端响应一致；
4. `src/brokers/futu/portfolio.py` 的账户发现、币种换算、平均成本和只读边界；
5. `src/services/moomoo_daily_report_service.py` 和 `moomoo_daily_report_scheduler.py` 的日报生成、单飞和调度语义；
6. `main.py` 的服务线程、信号处理和端口释放逻辑；
7. `.env.example`、中英文完整指南和 `docs/CHANGELOG.md` 是否继续与运行时一致。

### 最低验证清单

```bash
# 后端相关回归
./.venv/bin/python -m pytest \
  tests/test_futu_distribution_contract.py \
  tests/test_futu_portfolio_service.py \
  tests/test_moomoo_ai_context.py \
  tests/test_moomoo_daily_report.py \
  tests/test_moomoo_daily_report_api.py \
  tests/test_agent_chat_api.py \
  tests/test_data_tools_portfolio_snapshot.py \
  tests/test_notification_sender.py

# 前端
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

有可用的已登录 OpenD 时，还应启动 WebUI 并执行一次只读验收：

1. 打开 `/account`，确认美股、港股及币种显示正确；
2. 刷新持仓，确认没有重复账户或重复证券；
3. 从持仓进入 AI 问股，确认新建独立对话；
4. 分别验证 Discord 单条发送与自动发送；
5. 按 `Ctrl+C` 退出后确认 WebUI 端口已释放。

## 维护规则

- 新增 fork 专属功能时，在本文补充能力、入口、配置、依赖和同步风险；
- 新增 Python 直接运行时依赖时同步修改 `requirements.txt`；
- 新增前端依赖时使用 npm 更新 `package.json` 与 lockfile；
- 新增配置项时同步修改 `.env.example` 和对应专题文档；
- 用户可见行为变化继续按仓库约定更新 `docs/CHANGELOG.md`；
- 不在本文记录真实账户数据、持仓、密钥、Webhook URL 或本机私有路径。
