from typing import Dict

import httpx

CREATE_URL = "https://yuanbao.tencent.com/api/user/agent/conversation/create"
CLEAR_URL = "https://yuanbao.tencent.com/api/user/agent/conversation/v1/clear"

DEFAULT_TIMEOUT = 60


class ConversationCreationError(Exception):
    pass


class ConversationRemoveError(Exception):
    pass


async def create_conversation(agent_id: str, headers: Dict[str, str], timeout: int = DEFAULT_TIMEOUT) -> str:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(CREATE_URL, json={"agentId": agent_id}, headers=headers, timeout=timeout)

            if response.status_code != 200:
                raise Exception(f"Request failed. Status code: {response.status_code}, Response: {response.text}")

            try:
                json_data = response.json()
            except ValueError:
                raise Exception(f"Failed to parse response as JSON. Response: {response.text}")

            if "id" not in json_data:
                raise Exception(f"Failed to find 'id' in response JSON. Response: {response.text}")

            return json_data["id"]

    except Exception as e:
        raise ConversationCreationError(e)


async def remove_conversation(chat_id: str, headers: Dict[str, str], timeout: int = DEFAULT_TIMEOUT) -> None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                CLEAR_URL,
                json={"conversationIds": [chat_id], "uiOptions": {"noToast": True}},
                headers=headers,
                timeout=timeout,
            )

            if response.status_code != 200:
                raise Exception(f"Request failed. Status code: {response.status_code}, Response: {response.text}")

    except Exception as e:
        raise ConversationRemoveError(e)
