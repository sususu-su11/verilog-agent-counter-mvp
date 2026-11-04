# Counter MVP v3.3 — 实际测试记录

**2026-11-04 | 仅代码级离线验证 | 不签发自主 PASS**

**v3.3 变更**：仅 `public_mock` 不再调用 `require_rootless()`，允许操作者使用东京 VM 的 rootful `/var/run/docker.sock`。经模拟 rootful 条件，公开 MOCK 启动策略允许；`production` 仍拒绝 rootful。其余禁止降级、无 Inference key、固定 Demo ID、限流和并发限制保持。**没有执行东京 VM 的实际 Docker 启动，因此不宣称公开 Demo 验收通过。**

本文件已重写，取代 v2 报告。以下命令在本次提供补丁的本地执行环境内实际执行；它们**不能**证明隔离 VM、真实 Docker/Icarus 仿真或 Vultr Serverless Inference 成功。

## 已执行命令和实际输出

```text
$ python3 -m trusted.verify_manifest
MANIFEST_OK: counter4_sync_v1 26 assets

$ python3 -W error::ResourceWarning -m unittest discover -s tests -v
Ran 22 tests in 0.241s
OK

$ node --check app/static/app.js
(exit 0, no output)

$ bash -n deploy.sh
(exit 0, no output)

$ python3 -m compileall -q app trusted sandbox scripts tests
(exit 0, no output)

$ test ! -d review_inputs
(exit 0 — directory absent)

$ command -v docker
(no executable)
$ command -v iverilog
(no executable)
```

上述 22 项是离线 Python unittest，含原有策略/伪造协议/接口与账本检查、公开 MOCK 固定 ID/限流/并发校验，并新增 production 模式仍要求 rootless 的回归（固定 demo ID 与 API 禁止项、限流、并发槽、生产启动限制、digest/标签静态检查）。`test_synthetic_protocol_fixture_only` 的正例**是 Python 合成轨迹，不是真实 RTL 通过**。完整 unittest 控制台日志可另附 `v3_3_unittest.log`。

## 已实现但未在本机执行的真实回归

需要具备 Docker、Icarus 的**专用 VM**，切勿以 MOCK 冒充 live inference。

```bash
# 先在 VM 设置并核实 .env，构建沙箱镜像、确保无其他正在运行的 Verilog Agent 作业
./deploy.sh
set -a; . ./.env; set +a
python3 -m scripts.real_sandbox_regression
python3 -m scripts.private_accept

# 单独的公网 MOCK VM（不在私人 VM 上混用）
# 在专用无敏感数据的 VM 接受 rootful docker.sock 风险并确认硬费用边界后：
./deploy.sh --public-mock
python3 -m scripts.public_mock_accept
```

`scripts.real_sandbox_regression` 必须证明：宿主在 `/tmp/verilog-agent-host-sentinel/token` 存放随机 token、容器不读取该文件；10 个隔离探针、trusted chaos TB 伪造 `PASS`/`VLTB1`/`@@RESULT@@` 不产生 host PASS；每次有 `verilog-agent=1` 标签的容器都销毁；正确及故障 counter 的独立 host verdict 符合预期。

CI 增加了 `docker-containment-regression` job，但**当前未观察其 GitHub Actions 运行结果**；不能把 workflow 文件存在当作测试成功。这里没有 Docker 与 Icarus，所以真实容器探针是**未验收**。

## 不得宣称的证据

- 未确认 VM 部署、rootless/rootful 守护进程、实际映像拉取或安装在容器内的 `iverilog` 版本。
- 未核验用户提供的两个基础镜像 digest 在目标 VM 可拉取（仅按指定值固定）。
- 未执行公网可达性/滥用压力测试、宿主 Docker 控制面攻击测试。
- 未调用 Vultr Inference，没有 live 推理流水线、费用保障、录屏或 LabLab 提交证明。
- GitHub 远端可写性与推送结果应独立记录；本地测试不等于远端 CI 绿灯。

**判定责任：** 独立维护者收集目标 VM 与 GitHub Actions 的真实日志后决定是否接受；本文件仅记录本地运行事实和待验项。

## GitHub 发布尝试（单独于代码验收）

目标 `sususu-su11/verilog-agent-counter-mvp`。GitHub 连接读取到仓库时权限为 `pull=true, push=false`；本地 Git 已生成 `main` 初始提交。执行 `GIT_TERMINAL_PROMPT=0 git push -u origin main` 返回 **exit 128**，错误为 `Could not resolve host: github.com`。远端没有完成推送，**不宣称 GitHub CI 已通过**。交付 `*.bundle` 可在拥有 GitHub 写权限/网络的机器上导入并推送，见 `PUSH_INSTRUCTIONS.md`。
