#!/usr/bin/env bash
# =============================================================================
# bench_serving.sh — 使用 sglang.bench_serving 对第三方 OpenAI 兼容接口进行压测
#
# 用法:
#   bash benchmark/bench_serving.sh [选项]
#
# 常用选项:
#   --num-prompts N        发送的请求总数 (默认: 20)
#   --dataset-name sharegpt 数据集名称
#   --dataset-path /Volumes/S500Pro/token/ShareGPT_V3_unfiltered_cleaned_split.json 数据集本地路径（适用于已经预下载好的情况）
#   --request-rate R       每秒请求数, inf 表示立即全发 (默认: inf)
#   --max-concurrency N    最大并发数 (默认: 5)
#   --random-input-len N   随机输入长度 (默认: 128)
#   --random-output-len N  随机输出长度 (默认: 512)
#   --output-file FILE     JSONL 结果文件路径 (默认: 自动生成时间戳文件名)
#   --tokenizer HF_ID      用于 token 计数的 HuggingFace tokenizer (默认: THUDM/glm-4-9b-chat)
#                          注意：与 --model 无关，仅用于内部 token 计数，不影响 API 请求
#   --output-details       是否在 JSONL 中输出每请求详情 (默认: 启用)
#   --dry-run              仅打印命令，不实际执行
# =============================================================================

set -euo pipefail

# ── 0. 加载 .env（与 locustfile.py 保持一致）─────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    echo "📄 加载环境变量: $ENV_FILE"
    # 仅导出非注释、非空行
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
else
    echo "⚠️  未找到 .env 文件: $ENV_FILE，继续使用当前环境变量..."
fi

# ── 1. 核心参数（对应 locustfile.py 的配置）──────────────────────────────
# API Key：优先读取 OPENAI_API_KEY，否则读取 API_KEY（与 locustfile.py 一致）
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    if [[ -n "${API_KEY:-}" ]]; then
        export OPENAI_API_KEY="$API_KEY"
        echo "ℹ️  使用 API_KEY 作为 OPENAI_API_KEY"
    else
        echo "❌ 错误: 未设置 API_KEY 或 OPENAI_API_KEY 环境变量，请在 .env 中配置"
        exit 1
    fi
fi

# 目标接口（对应 locustfile.py 中的 host + url）
BASE_URL="${BENCH_BASE_URL:-https://www.sophnet.com}"
API_PATH="${BENCH_API_PATH:-/api/open-apis/v1}"   # sglang 会追加 /chat/completions

# 模型名（对应 locustfile.py 中的 self.model = "GLM-5"）
# 注意：此名称仅用于 API 请求体中的 model 字段，不用于加载权重
MODEL="${BENCH_MODEL:-GLM-5}"

# Tokenizer：sglang.bench_serving 内部需要一个真实的 HuggingFace tokenizer
# 用于统计 token 数量，与 MODEL 名称无关，不影响 API 请求目标
# GLM-5 的官方 tokenizer 托管在 zai-org/GLM-5（需要 trust_remote_code=True）
TOKENIZER="${BENCH_TOKENIZER:-zai-org/GLM-5}"

# ── 2. 默认压测参数 ────────────────────────────────────────────────────────
NUM_PROMPTS=20
REQUEST_RATE="inf"         # inf = 立即全部发出（最大压力）
MAX_CONCURRENCY=5
RANDOM_INPUT_LEN=128       # 随机输入 token 数（近似 prompt tokens）
RANDOM_OUTPUT_LEN=512      # 随机输出 token 数（近似 max_tokens）
RANDOM_RANGE_RATIO=0.5     # 长度随机范围比例

# 结果输出
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_FILE="${BENCH_OUTPUT_FILE:-$SCRIPT_DIR/results/bench_${TIMESTAMP}.jsonl}"
OUTPUT_DETAILS="--output-details"   # 启用每请求详情（对应 locustfile.py 的细粒度指标）

# 数据集本地路径（设置后将使用 sharegpt 模式，避免重新下载）
DATASET_PATH="${BENCH_DATASET_PATH:-}"

DRY_RUN=false

# ── 3. 解析命令行参数 ──────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --num-prompts)       NUM_PROMPTS="$2";      shift 2 ;;
        --request-rate)      REQUEST_RATE="$2";     shift 2 ;;
        --max-concurrency)   MAX_CONCURRENCY="$2";  shift 2 ;;
        --random-input-len)  RANDOM_INPUT_LEN="$2"; shift 2 ;;
        --random-output-len) RANDOM_OUTPUT_LEN="$2";shift 2 ;;
        --output-file)       OUTPUT_FILE="$2";      shift 2 ;;
        --no-output-details) OUTPUT_DETAILS="";     shift   ;;
        --model)             MODEL="$2";            shift 2 ;;
        --tokenizer)         TOKENIZER="$2";        shift 2 ;;
        --dataset-path)      DATASET_PATH="$2";     shift 2 ;;
        --base-url)          BASE_URL="$2";         shift 2 ;;
        --dry-run)           DRY_RUN=true;          shift   ;;
        *)
            echo "❌ 未知参数: $1"
            echo "用法: bash $0 [--num-prompts N] [--request-rate R] [--max-concurrency N]"
            echo "           [--random-input-len N] [--random-output-len N]"
            echo "           [--output-file FILE] [--no-output-details]"
            echo "           [--model MODEL] [--tokenizer HF_TOKENIZER_ID]"
            echo "           [--dataset-path /path/to/ShareGPT.json]"
            echo "           [--base-url URL] [--dry-run]"
            exit 1
            ;;
    esac
done

# ── 4. 创建结果目录 ────────────────────────────────────────────────────────
mkdir -p "$(dirname "$OUTPUT_FILE")"

# ── 5. 构建完整的 base-url（包含 API 路径前缀）────────────────────────────
# sglang-oai-chat 后端会在 base-url 后追加 /chat/completions
# 所以这里需要把完整路径（除去 /chat/completions 结尾）传入
FULL_BASE_URL="${BASE_URL}${API_PATH}"

# ── 6. 打印测试配置摘要 ────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  🚀 SGLang Bench Serving — 压测配置摘要"
echo "============================================================"
echo "  目标地址   : $FULL_BASE_URL"
echo "  API 模型名 : $MODEL  (仅用于请求体 model 字段)"
echo "  Token 计数 : $TOKENIZER  (HuggingFace tokenizer，仅用于 token 统计)"
if [[ -n "$DATASET_PATH" ]]; then
    echo "  数据集     : $DATASET_PATH  [本地 sharegpt 模式]"
else
    echo "  数据集     : random 模式 (输入~${RANDOM_INPUT_LEN} / 输出~${RANDOM_OUTPUT_LEN} tokens)"
fi
echo "  请求总数   : $NUM_PROMPTS"
echo "  请求速率   : $REQUEST_RATE req/s"
echo "  最大并发   : $MAX_CONCURRENCY"
echo "  结果文件   : $OUTPUT_FILE"
echo "============================================================"
echo ""
echo "  📊 将统计以下指标（对应 locustfile.py）:"
echo "     ✅ TTFT  — 首字时延 (Time to First Token, ms)"
echo "     ✅ TPOT  — 单 Token 生成耗时 (ms)"
echo "     ✅ ITL   — 逐 Token 间隔延迟 (Inter-Token Latency, ms)"
echo "     ✅ E2E   — 端到端请求延迟 (End-to-End Latency, ms)"
echo "     ✅ 吞吐量 — 请求/秒、输入 Tok/s、输出 Tok/s、总 Tok/s"
echo "     ✅ QPM   — 每分钟请求数 (= req/s × 60)"
echo "     ✅ Output TPM — 每分钟输出 Token 数 (= output tok/s × 60)"
echo "     ✅ Total TPM  — 每分钟总 Token 数 (= total tok/s × 60)"
echo "     ✅ Output Tokens / req — 每请求输出 Token 数"
echo "     ✅ Total Tokens  / req — 每请求总 Token 数"
echo "============================================================"
echo ""

# ── 7. 组装 sglang.bench_serving 命令 ─────────────────────────────────────
CMD=(
    python3 -m sglang.bench_serving
    # 后端：Chat Completions OpenAI 兼容接口（POST /v1/chat/completions）
    --backend          sglang-oai-chat

    # 目标服务器
    --base-url         "$FULL_BASE_URL"

    # 模型名（仅用于填充 API 请求体中的 model 字段，不加载权重）
    --model            "$MODEL"

    # Tokenizer（用于 token 计数，必须是 HuggingFace 上真实存在的 tokenizer）
    # 与 --model 完全独立，不影响实际 API 调用目标
    --tokenizer        "$TOKENIZER"

    # 数据集配置：
    # - 若设置了本地 DATASET_PATH，使用 sharegpt 模式加载真实对话，不下载
    # - 否则使用 random 模式（random 模式也会尝试下载 ShareGPT，若无本地文件会失败）
)
if [[ -n "$DATASET_PATH" ]]; then
    if [[ ! -f "$DATASET_PATH" ]]; then
        echo "❌ 数据集文件不存在: $DATASET_PATH"
        exit 1
    fi
    CMD+=(
        --dataset-name  sharegpt
        --dataset-path  "$DATASET_PATH"
    )
else
    CMD+=(
        --dataset-name     random
        --random-input-len  "$RANDOM_INPUT_LEN"
        --random-output-len "$RANDOM_OUTPUT_LEN"
        --random-range-ratio "$RANDOM_RANGE_RATIO"
    )
fi

# 追加公共参数
CMD+=(
    # 请求数量与速率
    --num-prompts      "$NUM_PROMPTS"
    --request-rate     "$REQUEST_RATE"
    --max-concurrency  "$MAX_CONCURRENCY"

    # 预热请求（避免冷启动影响数据）
    --warmup-requests 1

    # 结果输出
    --output-file      "$OUTPUT_FILE"
)

# 可选: 每请求详情
if [[ -n "$OUTPUT_DETAILS" ]]; then
    CMD+=("--output-details")
fi

# ── 8. 执行 ────────────────────────────────────────────────────────────────
echo "▶ 执行命令:"
echo "   ${CMD[*]}"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "🔸 [dry-run 模式，已跳过实际执行]"
    exit 0
fi

"${CMD[@]}"

# ── 9. 执行后处理：从 JSONL 提取并换算 QPM / TPM ──────────────────────────
echo ""
echo "============================================================"
echo "  📈 额外指标换算（与 locustfile.py 对齐）"
echo "============================================================"

if [[ -f "$OUTPUT_FILE" ]]; then
    # 读取最新一条记录（尾行）
    LAST=$(tail -n 1 "$OUTPUT_FILE")

    # 用 python3 解析 JSON 并打印换算结果
    python3 - <<PYEOF
import json, sys

try:
    data = json.loads("""$LAST""")
except Exception as e:
    print(f"  ⚠️  无法解析 JSONL: {e}")
    sys.exit(0)

req_s        = data.get("request_throughput", 0)
out_tok_s    = data.get("output_throughput", 0)
total_tok_s  = data.get("total_throughput", 0)
completed    = data.get("completed", 0)
total_out    = data.get("total_output_tokens", 0)
total_in     = data.get("total_input_tokens", 0)

qpm          = req_s * 60
output_tpm   = out_tok_s * 60
total_tpm    = total_tok_s * 60
avg_out_tok  = total_out / completed if completed else 0
avg_total_tok= (total_in + total_out) / completed if completed else 0

ttft_mean    = data.get("mean_ttft_ms", "N/A")
ttft_p99     = data.get("p99_ttft_ms", "N/A")
tpot_mean    = data.get("mean_tpot_ms", "N/A")
itl_mean     = data.get("mean_itl_ms", "N/A")
e2e_mean     = data.get("mean_e2e_latency_ms", "N/A")

print(f"  5_QPM (每分钟请求数)          : {qpm:.1f}")
print(f"  6_Output_TPM (每分钟输出Token): {output_tpm:.0f}")
print(f"  7_Total_TPM  (每分钟总Token)  : {total_tpm:.0f}")
print(f"  3_Avg_Output_Tokens/req       : {avg_out_tok:.1f}")
print(f"  4_Avg_Total_Tokens/req        : {avg_total_tok:.1f}")
print()
print(f"  1_TTFT_Mean (首字时延均值 ms) : {ttft_mean}")
print(f"     TTFT_P99  (99th percentile): {ttft_p99}")
print(f"  2_TPOT_Mean (单字耗时均值 ms) : {tpot_mean}")
print(f"     ITL_Mean  (逐Token间隔 ms) : {itl_mean}")
print(f"     E2E_Mean  (端到端延迟 ms)  : {e2e_mean}")
print()
print(f"  完成请求数                    : {completed}")
print(f"  结果文件                      : $OUTPUT_FILE")
PYEOF
else
    echo "  ⚠️  未找到结果文件: $OUTPUT_FILE"
fi

echo "============================================================"
echo "  ✅ 压测完成！"
echo "============================================================"
