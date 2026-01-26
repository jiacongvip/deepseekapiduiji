import asyncio
import json
import uuid
import aiohttp
from src.pool.session_pool import DoubaoSession

async def main():
    # Load session
    with open('session.json', 'r') as f:
        data = json.load(f)
        session_data = data[0]
        session = DoubaoSession(**session_data)

    print(f"Loaded session: {session.web_id}")

    # Params
    params = "&".join([
        "aid=497858",
        f"device_id={session.device_id}",
        "device_platform=web",
        "language=zh",
        "pc_version=2.23.2",
        "pkg_type=release_version",
        "real_aid=497858",
        "region=CN",
        "samantha_web=1",
        "sys_region=CN",
        f"tea_uuid={session.tea_uuid}",
        "use-olympus-account=1",
        "version_code=20800",
        f"web_id={session.web_id}"
    ])
    
    url = "https://www.doubao.com/chat/completion?" + params
    
    prompt = "你好"
    conversation_id = "" # New conversation
    
    # New structure based on capture
    body = {
        "client_meta": {
            "local_conversation_id": f"local_{int(uuid.uuid4().int % 10000000000000000)}",
            "conversation_id": conversation_id,
            "bot_id": "7338286299411103781", # Hardcoded for now, default Doubao bot?
            "last_section_id": "",
            "last_message_index": None
        },
        "messages": [
            {
                "local_message_id": str(uuid.uuid4()),
                "content_block": [
                    {
                        "block_type": 10000,
                        "content": {
                            "text_block": {
                                "text": prompt,
                                "icon_url": "",
                                "icon_url_dark": "",
                                "summary": ""
                            },
                            "pc_event_block": ""
                        },
                        "block_id": str(uuid.uuid4()),
                        "parent_id": "",
                        "meta_info": [],
                        "append_fields": []
                    }
                ],
                "message_status": 0
            }
        ],
        "option": {
            "send_message_scene": "",
            "create_time_ms": 1769442368441, # Maybe update this?
            "collect_id": "",
            "is_audio": False,
            "answer_with_suggest": False,
            "tts_switch": False,
            "need_deep_think": 0,
            "click_clear_context": False,
            "from_suggest": False,
            "is_regen": False,
            "is_replace": False,
            "disable_sse_cache": False,
            "select_text_action": "",
            "resend_for_regen": False,
            "scene_type": 0,
            "unique_key": str(uuid.uuid4()),
            "start_seq": 0,
            "need_create_conversation": True,
            "conversation_init_option": {
                "need_ack_conversation": True
            },
            "regen_query_id": [],
            "edit_query_id": [],
            "regen_instruction": "",
            "no_replace_for_regen": False,
            "message_from": 0,
            "shared_app_name": "",
            "sse_recv_event_options": {
                "support_chunk_delta": True
            },
            "is_ai_playground": False
        },
        "ext": {
            "conversation_init_option": "{\"need_ack_conversation\":true}",
            "fp": "verify_mkvcafny_Mhzifkl9_tgpD_4VAm_BMpL_NkIvu9EAd8t2", # This might need to be dynamic or from session?
            "use_deep_think": "0",
            "commerce_credit_config_enable": "0",
            "sub_conv_firstmet_type": "1"
        }
    }
    
    headers = {
        'content-type': 'application/json',
        'accept': 'text/event-stream',
        'agw-js-conv': 'str',
        'cookie': session.cookie,
        'origin': "https://www.doubao.com",
        'referer': f"https://www.doubao.com/chat/{session.room_id}",
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0',
        "x-flow-trace": session.x_flow_trace
    }
    
    print("Sending request...")
    print(f"URL: {url}")
    print(f"Body: {json.dumps(body, indent=2)}")
    
    try:
        async with aiohttp.ClientSession() as aio_session:
            async with aio_session.post(url=url, headers=headers, json=body) as response:
                print(f"Status: {response.status}")
                if response.status != 200:
                    text = await response.text()
                    print(f"Error: {text}")
                else:
                    async for chunk in response.content.iter_chunked(1024):
                        print(chunk.decode('utf-8', errors='replace'))
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())
