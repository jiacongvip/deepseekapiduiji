import json
import time
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from src.const import MODEL_MAPPING
from src.schemas.chat import ChatCompletionChunk, Choice, ChoiceDelta, Message


def get_model_info(model_name: str) -> Optional[Dict]:
    return MODEL_MAPPING.get(model_name.lower(), None)


def parse_messages(messages: List[Message]) -> str:
    only_user_message = True
    for m in messages:
        if m.role == "user":
            only_user_message = False
            break
    if only_user_message:
        prompt = "\n".join([f"{m.role}: {m.content}" for m in messages])
    else:
        prompt = "\n".join([f"{m.content}" for m in messages])
    return prompt


async def process_response_stream(
    response: httpx.Response, model_id: str
) -> AsyncGenerator[str, None]:
    def _create_chunk(content: str, finish_reason: Optional[str] = None) -> str:
        choice_delta = ChoiceDelta(content=content)
        choice = Choice(delta=choice_delta, finish_reason=finish_reason)
        chunk = ChatCompletionChunk(
            created=int(time.time()), model=model_id, choices=[choice]
        )
        return chunk.model_dump_json(exclude_unset=True)

    status = ""
    start_word = "data: "
    finish_reason = "stop"
    async for line in response.aiter_lines():
        if not line or not line.startswith(start_word):
            continue
        data: str = line[len(start_word) :]

        if data == "[DONE]":
            yield _create_chunk("", finish_reason)
            yield "[DONE]"
            break
        elif not data.startswith("{"):
            continue

        try:
            chunk_data: Dict = json.loads(data)
            
            # 处理消息内容
            content = ""
            if chunk_data.get("type") == "text":
                content = chunk_data.get("msg", "")
            
            # 处理引用来源 (reference)
            # 根据用户提供的真实数据，引用信息包含在 speechType="search_with_text" 的 speech 中
            # 结构为 content[0].docs，或者 type="searchGuid" 的 content 中
            
            # 检查 searchGuid 类型，这通常是搜索结果
            if chunk_data.get("type") == "searchGuid":
                docs = chunk_data.get("docs", [])
                if docs:
                    ref_text = "\n\n**引用来源**：\n"
                    for i, doc in enumerate(docs):
                        title = doc.get('title', '未知来源')
                        url = doc.get('url', '#')
                        ref_text += f"{i+1}. [{title}]({url})\n"
                    content += ref_text
                    
            # 之前的 reference 类型处理保留作为 fallback
            if chunk_data.get("type") == "reference":
                # 假设 references 字段是一个列表，包含引用信息
                refs = chunk_data.get("references", [])
                
                # 如果 references 为空，尝试从 msg 中解析（如果 msg 是 JSON 字符串）
                if not refs and "msg" in chunk_data:
                    try:
                        # 有时候 msg 字段可能包含引用信息的 JSON 字符串
                        # 但这里我们先假设它就是 references 列表，或者需要进一步探索
                        # 如果没有实际抓包数据，我们只能尝试打印出来看看
                        # 为了不破坏输出，我们暂时注释掉打印
                        # print(f"Reference chunk: {chunk_data}")
                        pass
                    except:
                        pass
                
                if refs:
                    ref_text = "\n\n**引用来源**：\n"
                    for i, ref in enumerate(refs):
                        # 尝试获取 title 和 url，如果没有则显示 Unknown
                        title = ref.get('title', '未知来源')
                        url = ref.get('url', '#')
                        ref_text += f"{i+1}. [{title}]({url})\n"
                    content += ref_text
                
                # 如果 type 是 reference 但 content 仍为空，且 msg 有内容，则直接显示 msg
                # 这可能是为了防止漏掉某些非标准格式的引用
                if not content and chunk_data.get("msg"):
                    # 只有当 msg 看起来不像 JSON 时才显示
                    if not chunk_data["msg"].strip().startswith("{"):
                        content += f"\n\n参考资料: {chunk_data['msg']}\n"

            # 如果是 tips 类型，通常是建议问题，可以忽略或作为特定格式处理
            if chunk_data.get("type") == "tips":
                continue
            
            # 如果是 meta 类型，包含 token 使用情况等
            if chunk_data.get("type") == "meta":
                if chunk_data.get("stopReason"):
                    finish_reason = chunk_data["stopReason"]
                continue

            if content:
                yield _create_chunk(content)
                
        except json.JSONDecodeError:
            continue
