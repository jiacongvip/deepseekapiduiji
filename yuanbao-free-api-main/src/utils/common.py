from typing import Dict


def generate_headers(request: dict, token: str) -> Dict[str, str]:
    # 尝试从请求体或 token 中提取参数，提供默认值防止报错
    hy_source = request.get('hy_source', 'web')
    hy_user = request.get('hy_user', '')
    agent_id = request.get('agent_id', 'na')
    
    return {
        "Cookie": f"hy_source={hy_source}; hy_user={hy_user}; hy_token={token}",
        "Origin": "https://yuanbao.tencent.com",
        "Referer": f"https://yuanbao.tencent.com/chat/{agent_id}",
        "X-Agentid": agent_id,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    }
