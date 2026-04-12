import os
import random
import sys
from dotenv import load_dotenv
import time
import json
import threading
from locust import HttpUser, FastHttpUser, task, between, events
from locust import argument_parser
import requests.exceptions

load_dotenv()  # Load variables from .env

# ── ShareGPT Dataset 支持 ─────────────────────────────────────────────
# 命令行参数：
#   --dataset        本地 ShareGPT JSON 文件路径
#   --dataset-size   从数据集中采样的条目数量（0 = 全量，默认 1000）
#   --min-tokens     过滤掉 prompt 字符数少于此值的条目（默认 0，不过滤）
# 示例：
#   locust -f benchmark/locustfile.py --dataset /path/to/ShareGPT_V3.json

@events.init_command_line_parser.add_listener
def add_custom_arguments(parser, **kwargs):
    parser.add_argument(
        "--dataset",
        type=str,
        default="",
        help="本地 ShareGPT JSON 文件路径（不设置则使用固定 prompt）",
        env_var="LOCUST_DATASET",
    )
    parser.add_argument(
        "--dataset-size",
        type=int,
        default=1000,
        help="从数据集中采样的条目数量（0 = 全量，默认 1000）",
        env_var="LOCUST_DATASET_SIZE",
    )
    parser.add_argument(
        "--min-tokens",
        type=int,
        default=0,
        help="过滤掉字符数少于此值的 prompt（默认 0，不过滤）",
        env_var="LOCUST_MIN_TOKENS",
    )

# 全局 prompt 列表，由 test_start 加载
_prompt_pool: list[str] = []
_prompt_pool_lock = threading.Lock()


def _load_sharegpt_dataset(path: str, size: int, min_chars: int) -> list[str]:
    """从 ShareGPT JSON 文件中加载 human 侧的第一轮消息，构建 prompt 池。

    ShareGPT 格式：
    [
      {"id": "...", "conversations": [
        {"from": "human", "value": "..."},
        {"from": "gpt",   "value": "..."},
        ...
      ]},
      ...
    ]

    只取每个对话的第一条 human 消息，过滤空消息和过短消息。
    """
    print(f"[Dataset] 正在加载 ShareGPT 数据集: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    prompts = []
    for item in data:
        convs = item.get("conversations", [])
        for turn in convs:
            if turn.get("from") == "human":
                text = (turn.get("value") or "").strip()
                if text and len(text) >= min_chars:
                    prompts.append(text)
                break  # 只取第一轮 human 消息

    # 随机打乱后按 size 截取
    random.shuffle(prompts)
    if size > 0:
        prompts = prompts[:size]

    print(f"[Dataset] 加载完成：共 {len(prompts)} 条 prompt（原始 {len(data)} 条对话）")
    return prompts


def _get_prompt(env) -> str:
    """返回一条待发送的 prompt 文本。

    若 prompt 池非空则随机采样；否则返回默认固定 prompt。
    """
    with _prompt_pool_lock:
        if _prompt_pool:
            return random.choice(_prompt_pool)
    # 回退：使用固定 prompt
    return f"请详细分析人工智能在未来医疗领域的应用，至少输出1000字。时间戳：{time.time()}"

# ── 全局统计计数器（线程安全）──────────────────────────────────────────
_stats_lock = threading.Lock()
_total_requests = 0          # 成功完成的请求总数
_total_output_tokens = 0     # 所有请求的 completion_tokens 累计
_total_tokens = 0            # 所有请求的 prompt+completion tokens 累计
_test_start_time = None      # 测试开始时间（由 test_start 事件写入）

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global _test_start_time, _total_requests, _total_output_tokens, _total_tokens, _prompt_pool
    with _stats_lock:
        _test_start_time = time.time()
        _total_requests = 0
        _total_output_tokens = 0
        _total_tokens = 0

    # 加载 ShareGPT 数据集（仅在 master / standalone 节点加载一次）
    dataset_path = getattr(environment.parsed_options, "dataset", "")
    dataset_size = getattr(environment.parsed_options, "dataset_size", 1000)
    min_tokens = getattr(environment.parsed_options, "min_tokens", 0)
    if dataset_path:
        try:
            loaded = _load_sharegpt_dataset(dataset_path, dataset_size, min_tokens)
            with _prompt_pool_lock:
                _prompt_pool = loaded
        except Exception as exc:
            print(f"[Dataset] 加载失败，将使用固定 prompt：{exc}")

def _report_tpm_qpm(completion_tokens: int, total_tokens: int):
    """每次请求结束后调用，累加计数并上报当前实时 TPM / QPM。"""
    global _total_requests, _total_output_tokens, _total_tokens
    with _stats_lock:
        _total_requests += 1
        _total_output_tokens += completion_tokens
        _total_tokens += total_tokens
        elapsed_min = (time.time() - _test_start_time) / 60.0
        if elapsed_min <= 0:
            return
        qpm = _total_requests / elapsed_min
        output_tpm = _total_output_tokens / elapsed_min
        total_tpm = _total_tokens / elapsed_min

    # 上报到 locust 统计面板（利用 response_time 字段存放速率值）
    events.request.fire(
        request_type="Rate",
        name="5_QPM_每分钟请求数",
        response_time=int(qpm),
        response_length=0,
        exception=None,
        context={},
    )
    events.request.fire(
        request_type="Rate",
        name="6_Output_TPM_每分钟输出Token数",
        response_time=int(output_tpm),
        response_length=0,
        exception=None,
        context={},
    )
    events.request.fire(
        request_type="Rate",
        name="7_Total_TPM_每分钟总Token数",
        response_time=int(total_tpm),
        response_length=0,
        exception=None,
        context={},
    )
# ─────────────────────────────────────────────────────────────────────

class LLMLoadTestUser(FastHttpUser):
    host = "https://www.sophnet.com"
    wait_time = between(0.0, 0.1)

    def on_start(self):
        api_key = os.environ.get("API_KEY")
        if not api_key:
            raise ValueError("环境变量 'API_KEY' 未设置，请配置后再运行测试。")
        self.api_key = api_key
        self.model = "GLM-5"
        # 设置请求的底层超时时间为 35 分钟，防止底层库过早断开
        # self.client.timeout = 2100

    @task
    def chat_completion(self):
        url = "/api/open-apis/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        prompt = _get_prompt(self.environment)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": True,
            # 兼容 OpenAI 格式的网关，要求在最后一个 chunk 返回 usage 统计
            "stream_options": {"include_usage": True},
            "max_tokens": 500
        }

        start_time = time.time()
        first_token_time = None
        prompt_tokens = 0
        completion_tokens = 0
        chunk_count = 0  # 用于在网关不返回 usage 时兜底估算 output tokens

        # timeout参数：(连接超时, 读取超时)，这里设置读取超时为 1800 秒 (30分钟)
        with self.client.post(url, json=payload, headers=headers, stream=True, catch_response=True, timeout=(10, 1800)) as response:

            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}: {response.text}")
                return

            try:
                def get_lines(resp):
                    if hasattr(resp, "iter_lines"):
                        for _line in resp.iter_lines():
                            yield _line
                    else:
                        pending = b""
                        for chunk in resp.stream:
                            if chunk:
                                pending += chunk
                                lines = pending.split(b"\n")
                                pending = lines.pop()
                                for l in lines:
                                    yield l
                        if pending:
                            yield pending

                for line in get_lines(response):
                    if line:
                        decoded_line = line.decode('utf-8').strip()
                        if decoded_line.startswith("data: ") and decoded_line != "data: [DONE]":
                            #print(decoded_line) ## ONLY DEBUG
                            try:
                                data = json.loads(decoded_line[6:])

                                # 1. 捕捉 TTFT (首字延迟，包含思考内容)
                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    # 只要有 content 或 reasoning_content 就算首字到达
                                    if first_token_time is None and (delta.get("content") or delta.get("reasoning_content")):
                                        first_token_time = time.time()
                                        ttft_ms = int((first_token_time - start_time) * 1000)
                                        events.request.fire(request_type="Metric", name="1_TTFT_首字时延(ms)", response_time=ttft_ms, response_length=0, exception=None, context={})

                                    # 统计有效 chunk 数量（用于在没有 usage 时估算总 Token）
                                    if delta.get("content") or delta.get("reasoning_content"):
                                        chunk_count += 1

                                # 2. 捕捉 Usage (Token 统计)
                                if "usage" in data and data["usage"]:
                                    prompt_tokens = data["usage"].get("prompt_tokens", 0)
                                    completion_tokens = data["usage"].get("completion_tokens", 0)

                            except json.JSONDecodeError:
                                pass

                # --- 结束后的指标计算 ---
                total_time_sec = time.time() - start_time
                total_time_ms = int(total_time_sec * 1000)

                # 如果网关没有返回 usage，用 chunk_count 兜底估算输出 Token
                if completion_tokens == 0:
                    completion_tokens = chunk_count

                # 指标 7: 空结果校验
                if completion_tokens == 0:
                    events.request.fire(request_type="Error", name="空结果_Empty_Result", response_time=total_time_ms, response_length=0, exception=None, context={})
                    response.failure("触发空结果：输出 Token 数为 0")
                    return

                # 指标 5: TPOT (每个输出 Token 平均耗时)
                if completion_tokens > 1 and first_token_time is not None:
                    # 耗时 = (总耗时 - 首字耗时) / (输出Token数 - 1)
                    tpot_ms = int(((time.time() - first_token_time) * 1000) / (completion_tokens - 1))
                    events.request.fire(request_type="Metric", name="2_TPOT_单字耗时(ms)", response_time=tpot_ms, response_length=0, exception=None, context={})

                # 将 Token 数量作为指标上报（技巧：利用 response_time 字段上报数字，方便后续查看均值）
                events.request.fire(request_type="Metric_Token", name="3_Output_Tokens_Per_Req", response_time=completion_tokens, response_length=0, exception=None, context={})
                events.request.fire(request_type="Metric_Token", name="4_Total_Tokens_Per_Req", response_time=(prompt_tokens + completion_tokens), response_length=0, exception=None, context={})

                # 上报 TPM / QPM 实时速率指标
                _report_tpm_qpm(completion_tokens, prompt_tokens + completion_tokens)

                # 正常完成
                response.success()

            except Exception as e:
                # 指标 8: 超过 30 分钟截断不算失败
                elapsed = time.time() - start_time
                if elapsed >= 1800:  # 30分钟
                    response.success() # 强制标记为成功
                    events.request.fire(request_type="Metric", name="30分钟超时截断(成功)", response_time=int(elapsed*1000), response_length=0, exception=None, context={})
                else:
                    response.failure(f"请求异常断开: {str(e)}")

if __name__ == "__main__":
    from locust.env import Environment
    from locust import run_single_user

    # 临时加一行打印，验证流式输出是否正常
    print("🚀 开始单步调试，直接打印大模型返回流...")

    # 将 LLMLoadTestUser 替换为你脚本里实际的类名
    run_single_user(LLMLoadTestUser)

