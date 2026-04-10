

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