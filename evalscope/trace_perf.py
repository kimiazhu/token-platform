import uuid, os
from typing import Dict, List, Union
from dotenv import load_dotenv

# 导入压测核心参数与启动器
from evalscope.perf.arguments import Arguments
from evalscope.perf.main import run_perf_benchmark

# 导入 EvalScope 的注册表
from evalscope.perf.plugin.registry import register_api, ApiRegistry

# 🔥 【绝杀技巧 1】：先引入官方的 openai 模块，确保官方的插件已被成功注册到系统里
import evalscope.perf.plugin.api.openai_api 

# 🔥 【绝杀技巧 2】：不去猜具体的类名，直接从注册表里把 api="openai" 的原装类提取出来当父类！
OpenAIBaseClass = ApiRegistry.get_class('openai')

load_dotenv()

@register_api('openai_with_uuid')
# 🔥 动态继承提取出来的官方类
class OpenAiuuidPlugin(OpenAIBaseClass):
    def build_request(self, messages: Union[List[Dict], str], param: Arguments = None) -> Dict:
        param = param or self.param
        
        # 执行官方原汁原味的 OpenAI 请求体组装逻辑
        payload = super().build_request(messages, param=param)
        
        # 动态注入全局唯一的 UUID 作为 user 字段！
        payload['user'] = str(uuid.uuid4())
        return payload

if __name__ == '__main__':
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise ValueError("环境变量 'API_KEY' 未设置，请配置后再运行测试。")
    task_cfg = {
        "url": "https://api.allall.ai/v1/chat/completions",
        "api_key": api_key,
        "model": "glm-5",
        
        # 【关键】依然调用咱们自定义的带 uuid 的插件
        "api": "openai_with_uuid",
        
        # 【保持开启】阻止那没用的预检发包
        "no_test_connection": True,  
        
        "number": 20,           
        "parallel": 10,         
        "rate": 2,
        "stream": True,
        "total_timeout": 180,
        "dataset": "openqa",
        "tokenizer_path": "/data/datasets/AI-ModelScope/tokenizer-glm-5",
        "dataset_path": "/data/datasets/AI-ModelScope/HC3-Chinese/open_qa.jsonl"
    }

    print("🚀 动态提取原生 OpenAI 插件成功！开始发送 UUID 并发请求...")
    run_perf_benchmark(task_cfg)