

## 单个节点测试：
```bash
locust -f benchmark/locustfile.py --headless -u 2 -r 2 -t 5m
```

## 多个节点测试：
```bash
# workers:
# 使用 nohup 将进程放到后台运行，并将日志输出到 worker.log
nohup locust -f locustfile.py --worker --master-host=<master_ip> > worker.log 2>&1 &
# 根据机器的 CPU 核心数，重复执行上述命令多次

############################################################################
# master:
locust -f benchmark/locustfile.py \
    --master \
    --headless \
    -u 2000 \
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
locust -f benchmark/locustfile.py --headless -u 100 -r 5 -t 300s \
  --dataset /Volumes/S500Pro/token/ShareGPT_V3_unfiltered_cleaned_split.json
# 全量加载，并过滤掉字符数少于 50 的短 prompt
locust -f benchmark/locustfile.py --headless -u 50 -r 5 -t 300s \
  --dataset /Volumes/S500Pro/token/ShareGPT_V3_unfiltered_cleaned_split.json \
  --dataset-size 0 \
  --min-tokens 50
```