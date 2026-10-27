# 政策性金融智能研究与业务工作台（Policy Finance Copilot）

面向政策性金融 / 政府性融资担保与再担保机构的 **AI 行业研究 + 业务工作台**：政策资讯采集与知识库、每日简报、研究报告写作、机构授信测算、额度看板，并提供微信 / 飞书机器人与 PPT 自动生成。

> ⚠️ **示例数据均为虚构**。`samples/` 中的机构名称（如「示例A融资担保有限公司」「示例省级融资再担保有限责任公司」）、台账与额度均为演示用途，不对应任何真实机构或真实业务。
>
> 示例场景：某省级再担保公司的再担保业务条线（仅作场景说明）。
>
> 口径版本 / 政策效力：授信结果写入 `app/m4/formula_spec.json` 的口径版本（不改变现有计算公式）；政策效力由人工核定。公式 DSL、失效日自动抽取后续再做。

## 功能概览

| 模块 | 说明 |
|---|---|
| **M1 财金协同知识库** | 查询模板 × 主题 × 地域的搜索驱动采集（Tavily / 阿里云 IQS）→ 权威发布方分级过滤 → 去重 → 正文抓取（SSRF 防护）→ AI 要点；FTS5 检索与语义问答。条目可人工核定效力（现行有效 / 已废止 / 已失效 / 未知），首页列出 90 天内到期；问答与检索对非现行有效附效力提示 |
| **M2 今日行业 Brief** | 取 M1 近 24h 条目，重要度打分、分级、模板化五栏简报，关键数字来源校验 |
| **M3 行业研究院** | 三 Agent 写作链路（研究写作 → 核对 → 润色）：知识库 + 联网检索 + 业务数据填数，自动生成引用来源登记表，导出 Word |
| **M4 机构授信管理** | 导入授信额度计算表 → 系数测算 → 人工调整（原因必填、留痕）→ 方案版本对比 → 导出 Excel / 请示 Word。每次重算把口径版本、参数版本与 calc.py 哈希写入结果。内部可在页面查阅「口径说明」；导出口径说明（单独文件或测算表中的工作表）仅系统管理员 |
| **M5 机构看板** | 上传四端口台账 → 汇总页 / 分机构页 → 预警、环比说明、图表、快照回溯、导出 |
| **PPT 生成 Agent** | 基于业务数据与研究报告生成可编辑 PPT（原生图表/表格、自动分页、水印） |
| **研究报告** | M3 报告定稿、导出、邮件发送（域名白名单 + 水印） |
| **微信 / 飞书机器人** | 私聊机器人查额度、预警、简报、研究报告，发起 PPT 生成；权限随绑定账号角色 |
| 其他 | 单机构自测 `/selftest`、管理员 / 用户 / 机构账号、导出水印、每日备份 |

## 架构

```
浏览器（原生 HTML/CSS/JS + ECharts 本地化）
        │
   Caddy（可选，HTTPS） ──► FastAPI（app/）
                              ├─ m1~m5 / ppt / wechat / feishu / mailer
                              ├─ llm/：OpenAI 兼容适配器（MiniMax、DeepSeek 等预设）
                              ├─ search/：Tavily、阿里云 IQS
                              └─ SQLite（FTS5）+ Fernet 加密的 Key 存储
```

目录：`app/` 后端 · `static/` 前端 · `samples/` 虚构示例数据 · `tests/` 测试 · `deploy/` Caddy / nginx / systemd 示例 · `docs/` 详细说明与机器人接入文档 · `scripts/` 辅助脚本。

## 快速开始（docker compose）

```bash
cp .env.example .env
mkdir -p backups && sudo chown 1000:1000 backups && chmod 700 backups
docker compose up -d --build
# 打开 http://localhost:8000
docker compose exec app cat /data/admin_initial_password.txt   # 管理员 admin 的随机初始密码，首次登录强制修改
```

公网 HTTPS 部署：修改 `deploy/Caddyfile` 中的 `your.domain.example` 与证书路径，然后 `docker compose --profile https up -d`。

本地开发：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
.venv/bin/python -m pytest -q tests/ --ignore-glob='tests/ui_*'
```

演示数据：M4 页「导入样例」、M5 页「一键导入样例」均读取 `samples/` 下的虚构 Excel（10 家虚构机构，数值随机生成）。可用 `python scripts/gen_sample_data.py`（需 LibreOffice）按固定种子重新生成。

## 配置

- 环境变量见 [`.env.example`](.env.example)。
- 大模型、联网搜索、飞书、微信、SMTP 的 Key 在 **系统管理** 页面录入，使用 `PH_SECRET_KEY`（或自动生成的 `secret.key`）加密存库，接口不返回明文。请妥善备份 `secret.key`。
- 机器人接入：[`docs/wechat_setup.md`](docs/wechat_setup.md)、[`docs/feishu_setup.md`](docs/feishu_setup.md)；更多细节见 [`docs/详细说明.md`](docs/详细说明.md)。

## 许可证

[MIT](LICENSE) © 2026 xiao sun
