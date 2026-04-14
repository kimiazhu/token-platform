

# LLM 性能压力测试 (Locust)

本项目使用 Locust 进行 LLM 接口的压力测试，支持流式输出、TTFT/TPOT 指标统计以及 ShareGPT 数据集采样。

## 环境变量配置

测试脚本会自动加载根目录下的 `.env` 文件。你可以通过环境变量或 `.env` 文件配置以下参数：

| 环境变量 | 含义 | 默认值 |
| :--- | :--- | :--- |
| `API_KEY` | **(必填)** 用于 API 认证的 Key | - |
| `BASE_URL` | 目标服务的 Base URL | `https://www.sophnet.com` |
| `API_PATH` | Chat Completion 接口路径 | `/api/open-apis/v1/chat/completions` |
| `MODEL` | 模型名称 | `GLM-5` |
| `LOCUST_DATASET` | 本地 ShareGPT JSON 数据集路径 | `""` (不设置则使用固定 prompt) |
| `LOCUST_DATASET_SIZE` | 从数据集中随机采样的 Prompt 数量 | `1000` (设置为 0 则全量加载) |
| `LOCUST_MIN_TOKENS` | 过滤掉字符数（注：代码中按字符长度过滤）少于此值的文本 | `0` |

---

## 单个节点测试：
```bash
locust -f benchmark/locustfile.py --headless -u 2 -r 2 -t 5m
```

## 多个节点测试：
```bash
# workers:
# 使用 nohup 将进程放到后台运行，并将日志输出到 worker.log
nohup locust -f benchmark/locustfile.py --worker --master-host=127.0.0.1 > worker.log 2>&1 &
# 根据机器的 CPU 核心数，重复执行上述命令多次

############################################################################
# master:
locust -f benchmark/locustfile.py \
    --master \
    --headless \
    -u 1000 \
    -r 50 \
    --run-time 10m \
    --expect-workers 3 \
    --csv=llm_test_results

```

## 使用 ShareGPT 数据集进行压测

~向后兼容：不传 --dataset 时，行为与原始版本完全相同，继续使用固定 prompt。~

```bash
# 从 ShareGPT 数据集随机取 1000 条 prompt 压测
# 数据集下载地址：wget https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json
# 如下载不到可以用hg镜像站：export HF_ENDPOINT=https://hf-mirror.com
locust -f benchmark/locustfile.py --headless -u 100 -r 5 -t 300s \
  --dataset /Volumes/S500Pro/token/ShareGPT_V3_unfiltered_cleaned_split.json

# 全量加载，并过滤掉字符数少于 50 的短 prompt
locust -f benchmark/locustfile.py --headless -u 50 -r 5 -t 300s \
  --dataset /Volumes/S500Pro/token/ShareGPT_V3_unfiltered_cleaned_split.json \
  --dataset-size 0 \
  --min-tokens 50
```