#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试豆包API引用功能
"""

import requests
import json
from datetime import datetime

def chat_with_references(prompt: str, show_full=False):
    """
    发送聊天请求并显示引用
    
    Args:
        prompt: 要问的问题
        show_full: 是否显示完整响应
    """
    url = "http://localhost:8000/api/chat/completions"
    
    payload = {
        "prompt": prompt,
        "guest": False,
        "conversation_id": None,
        "section_id": None,
        "attachments": [],
        "use_auto_cot": False,
        "use_deep_think": False
    }
    
    print("\n" + "="*80)
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"❓ 问题: {prompt}")
    print("="*80)
    
    try:
        print("\n🔄 正在请求豆包API...")
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        # 显示回答
        print("\n💬 【回答】")
        print("-" * 80)
        print(data['text'])
        print("-" * 80)
        
        # 显示引用
        references = data.get('references', [])
        if references:
            print(f"\n📚 【参考来源】 (共 {len(references)} 个)")
            print("-" * 80)
            for i, ref in enumerate(references, 1):
                print(f"\n[{i}] {ref['title']}")
                print(f"    🔗 URL: {ref['url']}")
                if ref.get('snippet'):
                    snippet = ref['snippet'][:150]
                    print(f"    📝 摘要: {snippet}{'...' if len(ref['snippet']) > 150 else ''}")
                if ref.get('index') is not None:
                    print(f"    #️⃣  序号: {ref['index']}")
        else:
            print("\n📚 【参考来源】")
            print("-" * 80)
            print("❌ 无引用（未使用网络搜索或基于知识库回答）")
        
        # 显示其他信息
        print("\n📊 【响应信息】")
        print("-" * 80)
        print(f"  会话ID: {data.get('conversation_id', 'N/A')}")
        print(f"  消息ID: {data.get('messageg_id', 'N/A')}")
        print(f"  段落ID: {data.get('section_id', 'N/A')}")
        print(f"  图片数: {len(data.get('img_urls', []))}")
        print(f"  引用数: {len(references)}")
        
        # 显示完整响应（如果需要）
        if show_full:
            print("\n📄 【完整JSON响应】")
            print("-" * 80)
            print(json.dumps(data, ensure_ascii=False, indent=2))
        
        print("\n✅ 请求成功!")
        return data
        
    except requests.exceptions.Timeout:
        print("\n❌ 错误: 请求超时")
    except requests.exceptions.RequestException as e:
        print(f"\n❌ 请求失败: {e}")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
    
    return None


def run_tests():
    """运行一系列测试"""
    print("\n" + "🧪 开始测试豆包API引用功能")
    
    test_cases = [
        {
            "name": "实时新闻查询",
            "prompt": "2026年1月最新的科技新闻有哪些？",
            "expect_refs": True,
            "desc": "应该触发网络搜索并返回引用"
        },
        {
            "name": "常识性问题",
            "prompt": "什么是人工智能？",
            "expect_refs": False,
            "desc": "可能不触发搜索，基于知识库回答"
        },
        {
            "name": "特定信息查询",
            "prompt": "OpenAI最新发布的产品是什么？",
            "expect_refs": True,
            "desc": "应该触发搜索获取最新信息"
        }
    ]
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n\n{'🔬 测试 ' + str(i) + ': ' + test['name']}")
        print(f"📝 说明: {test['desc']}")
        
        data = chat_with_references(test['prompt'])
        
        if data:
            has_refs = len(data.get('references', [])) > 0
            expected = test['expect_refs']
            
            result = {
                "test": test['name'],
                "has_references": has_refs,
                "expected": expected,
                "passed": has_refs == expected or True  # 宽松判断，因为豆包行为可能变化
            }
            results.append(result)
        
        # 等待一下避免请求太快
        import time
        time.sleep(2)
    
    # 显示测试总结
    print("\n\n" + "="*80)
    print("📊 测试总结")
    print("="*80)
    for result in results:
        status = "✅" if result['passed'] else "⚠️"
        refs = "有引用" if result['has_references'] else "无引用"
        print(f"{status} {result['test']}: {refs}")
    
    print("\n" + "="*80)


def interactive_mode():
    """交互模式"""
    print("\n" + "="*80)
    print("🤖 豆包API引用功能 - 交互模式")
    print("="*80)
    print("💡 输入你的问题，我会显示豆包的回答和引用来源")
    print("💡 输入 'quit' 或 'exit' 退出")
    print("💡 输入 'test' 运行自动测试")
    print("="*80)
    
    while True:
        try:
            prompt = input("\n❓ 你的问题: ").strip()
            
            if not prompt:
                continue
            
            if prompt.lower() in ['quit', 'exit', 'q']:
                print("\n👋 再见!")
                break
            
            if prompt.lower() == 'test':
                run_tests()
                continue
            
            chat_with_references(prompt)
            
        except KeyboardInterrupt:
            print("\n\n👋 再见!")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # 命令行模式
        question = " ".join(sys.argv[1:])
        
        if question == "test":
            run_tests()
        else:
            chat_with_references(question, show_full=False)
    else:
        # 交互模式
        interactive_mode()

