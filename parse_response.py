import base64
import pickle
import json
import argparse
import sys
import os

def parse_response_field(raw_string):
    """
    解析 evalscope 压测生成的 response_messages 字段
    """
    print(f"--- 开始解析 ---")
    
    # 截断显示，防止终端被超长字符串刷屏
    display_str = raw_string if len(raw_string) < 100 else raw_string[:100] + "..."
    print(f"读取到的字符串: '{display_str}'")
    
    try:
        # 第一步：进行 Base64 解码，将字符串还原为字节流
        decoded_bytes = base64.b64decode(raw_string)
        
        # 第二步：进行 Pickle 反序列化，将字节流还原为 Python 对象
        parsed_data = pickle.loads(decoded_bytes)
        
        print(f"解析成功！")
        print(f"数据类型: {type(parsed_data)}")
        print(f"解析结果: {parsed_data}")
        
        # 第三步：如果里面有数据，尝试进一步提取
        if isinstance(parsed_data, list) and len(parsed_data) > 0:
            print("\n发现数据内容，尝试提取详情:")
            for item in parsed_data:
                # 处理可能嵌套 JSON 字符串的情况
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        pass
                print(f"- {item}")
        elif isinstance(parsed_data, list) and len(parsed_data) == 0:
            print("\n提示: 这是一个空列表。通常代表网络请求失败，服务端没有返回任何数据（因此也没有 request_id）。")
            
        return parsed_data

    except base64.binascii.Error:
        print("错误: Base64 解码失败，请检查文件中的字符串是否完整且没有多余字符。")
    except pickle.UnpicklingError:
        print("错误: Pickle 反序列化失败，数据可能损坏或不是标准 Pickle 格式。")
    except Exception as e:
        print(f"发生未知错误: {e}")
        
    return None

def main():
    # 设置命令行参数解析
    parser = argparse.ArgumentParser(description="读取并解析 evalscope 的 response_messages 字段。")
    parser.add_argument("filepath", help="包含 base64 编码字符串的文本文件路径，例如 res.txt")
    
    args = parser.parse_args()
    
    # 检查文件是否存在
    if not os.path.exists(args.filepath):
        print(f"错误: 找不到文件 '{args.filepath}'")
        sys.exit(1)
        
    try:
        # 读取文件内容
        with open(args.filepath, 'r', encoding='utf-8') as f:
            # .strip() 用于移除开头和结尾可能包含的换行符或空格，确保 base64 解码正常
            raw_string = f.read().strip()
    except Exception as e:
        print(f"读取文件时发生错误: {e}")
        sys.exit(1)
        
    if not raw_string:
        print("错误: 文件内容为空。")
        sys.exit(1)
        
    # 执行解析
    parse_response_field(raw_string)

if __name__ == "__main__":
    main()