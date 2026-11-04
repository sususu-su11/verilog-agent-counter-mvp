# Counter MVP v3 修补记录（不签发独立 PASS）

基线：v2 本地修补包。此次为代码与审查文档增量，**未运行 Docker/Icarus、未部署 Vultr、未调用真实 Inference、未向 LabLab 提交**。

## 逐项结果

| 用户要求 | 修改位置 | 当前可确认事项 | VM 待验 |
|---|---|---|---|
| 重新整理测试证据、删除 review_inputs | `TEST_RESULTS.md`；移除 `review_inputs/` | 报告区分离线与真实 Docker；文件夹已不在源码包 | 无 |
| Host sentinel + chaos TB + label + regression | `sandbox/probe.py`, `trusted/chaos_tb.sv`, `app/docker_wrapper.py`, `scripts/real_sandbox_regression.py` | 源码与测试路径齐备，容器标签和拒绝协议有离线测试 | 主机 token、10 个探针、chaos、docker ps 标签清理 |
| 两个 FROM digest 与 Icarus 版本 | `Dockerfile`, `sandbox/Dockerfile`, `VERSIONS` | 按用户提供 digest 精确写入，Icarus 记录 `11.0-1.1` | 确认镜像可拉取并检查安装版本 |
| README lint/socket 风险 | `README.md` | 如实声明 regex lint 非安全沙箱，docker.sock 是控制面残余风险 | 审核 VM 上的 daemon 权限 |
| 公开 MOCK 固定 Demo | `app/config.py`, `app/main.py`, `app/agent.py`, `app/static/app.js`, `deploy.sh`, `docker-compose.yml`, `scripts/public_mock_accept.py` | 仅固定 ID、限流、并发、关 Swagger/Probe、rootless/显式开关、防降级均有单测 | 公网 VM 安全和真实 HTTP 验收 |

## 受审文件与验收

`trusted/manifest.json` 已随本次源码变更单独更新并固定 **26 个文件**（部署期间不允许生成新 hash）。所有受审代码和当前 manifest 应当**一起进入经过审核的 Git commit**，否则无法形成固定基线。

离线命令：

```bash
python3 -m trusted.verify_manifest
python3 -m unittest discover -s tests -v
node --check app/static/app.js
bash -n deploy.sh
```

真实 Docker 私有 VM：`./deploy.sh`，随后 `python3 -m scripts.real_sandbox_regression`、`python3 -m scripts.private_accept`。

独立公开 MOCK VM：`APP_ENV=public_mock` + `MOCK_LLM=1` + 无 API key + rootless Docker + 允许显式公网绑定后 `./deploy.sh --public-mock`；随后 `python3 -m scripts.public_mock_accept`。

**没有自动扣费脚本**；操作者自行确认 Vultr 信用金硬上限，不能把代码里的调用计数器当作不会扣银行卡的保证。`TEST_RESULTS.md` 是当前已执行命令的真实摘要，不是 VM PASS 证明。
