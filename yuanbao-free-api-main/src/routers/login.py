from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup
import time
import re
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

APPID = "wx12b75947931a04ec"
HEADERS = {
    "x-token": "",
    "x-instance-id": "1",
    "x-language": "zh-CN",
    "x-requested-with": "XMLHttpRequest",
    "x-operationsystem": "win",
    "x-channel": "10014",
    "x-id": "",
    "x-product": "bot",
    "x-appversion": "1.8.1",
    "x-source": "web",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0 app_lang/zh-CN product_id/TM_Product_App app_instance_id/2 os_version/10.0.19045 app_short_version/1.8.1 package_type/publish_release app/tencent_yuanbao app_full_version/1.8.1.610 app_theme/system app_version/1.8.1 os_name/windows c_district/0",
    "x-a3": "c2ac2b24fe3303043553b2b0300019319312",
}

WX_HEADERS = {
    "User-Agent": HEADERS["user-agent"]
}

@router.get("/login/qrcode")
async def get_qrcode():
    """获取微信登录二维码链接和UUID"""
    try:
        url = "https://open.weixin.qq.com/connect/qrconnect"
        params = {
            "appid": APPID,
            "scope": "snsapi_login",
            "redirect_uri": "https://yuanbao.tencent.com/desktop-redirect.html?&&bindType=wechat_login",
            "state": "",
            "login_type": "jssdk",
            "self_redirect": "true",
            "styletype": "",
            "sizetype": "",
            "bgcolor": "",
            "rst": "",
            "href": "",
        }
        response = requests.get(url, params=params, headers=WX_HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        qrcodes = soup.find_all("img", class_="js_qrcode_img web_qrcode_img")

        if not qrcodes:
            raise HTTPException(status_code=500, detail="未找到二维码元素")

        qrcode_src = qrcodes[0].get("src")
        uuid = qrcode_src.split("/")[-1]
        qrcode_url = f"https://open.weixin.qq.com{qrcode_src}"

        return JSONResponse(content={"uuid": uuid, "qrcode_url": qrcode_url})

    except Exception as e:
        logger.error(f"获取二维码失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/login/status")
async def check_login_status(uuid: str):
    """检查扫码状态"""
    if not uuid:
        raise HTTPException(status_code=400, detail="UUID不能为空")

    url = "https://lp.open.weixin.qq.com/connect/l/qrconnect"
    params = {"uuid": uuid, "_": int(time.time() * 1000)}
    
    try:
        response = requests.get(url, params=params, headers=WX_HEADERS, timeout=10)
        response.raise_for_status()
        
        # 解析响应
        # window.wx_errcode=408;window.wx_code=''; (等待扫码)
        # window.wx_errcode=404;window.wx_code=''; (已扫码，等待确认)
        # window.wx_errcode=405;window.wx_code='...'; (登录成功)
        
        pattern = r"window\.wx_errcode=(\d*);window\.wx_code='(.*)';"
        match = re.search(pattern, response.text)
        
        if not match:
            return JSONResponse(content={"status": "unknown", "msg": "解析响应失败"})
            
        errcode, wx_code = match.groups()
        
        if wx_code:
            # 登录成功，获取 Cookie
            login_url = "https://yuanbao.tencent.com/api/joint/login"
            data = {"type": "wx", "jsCode": wx_code, "appid": APPID}
            
            login_res = requests.post(login_url, json=data, headers=HEADERS, timeout=10)
            cookies = login_res.cookies.get_dict()
            
            if cookies:
                # 尝试获取 agent_id
                agent_id = "naQivTmsDa" # 默认值
                try:
                    # 访问主页获取 agent_id
                    home_url = "https://yuanbao.tencent.com/chat/"
                    # 使用 WX_HEADERS 或 HEADERS，这里用 WX_HEADERS 模拟浏览器访问
                    home_res = requests.get(home_url, cookies=cookies, headers=WX_HEADERS, timeout=10)
                    # 尝试从 URL 或页面内容中提取
                    # 页面可能重定向到 /chat/{agent_id}
                    if "/chat/" in home_res.url:
                        path_parts = home_res.url.split("/chat/")
                        if len(path_parts) > 1:
                            possible_id = path_parts[1].split("?")[0]
                            if possible_id:
                                agent_id = possible_id
                    
                    # 也可以尝试从页面内容匹配
                    if agent_id == "naQivTmsDa":
                        # 查找 window.__INITIAL_STATE__ 或类似配置
                        # 这是一个猜测的正则，用于匹配可能的 agentId
                        match_id = re.search(r'"agentId":"([^"]+)"', home_res.text)
                        if match_id:
                            agent_id = match_id.group(1)
                except Exception as e:
                    logger.error(f"获取 agent_id 失败: {e}")

                # 构造符合格式的 Cookie 字符串
                cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
                
                # 提取 hy_user 和 hy_token
                hy_user = cookies.get("hy_user", "")
                hy_token = cookies.get("hy_token", "")
                
                return JSONResponse(content={
                    "status": "success", 
                    "cookie": cookie_str,
                    "cookies_dict": cookies,
                    "agent_id": agent_id,
                    "hy_user": hy_user,
                    "hy_token": hy_token
                })
            else:
                return JSONResponse(content={"status": "failed", "msg": "登录成功但未获取到Cookie"})
                
        elif errcode == "408":
            return JSONResponse(content={"status": "waiting", "msg": "等待扫码"})
        elif errcode == "404":
            return JSONResponse(content={"status": "scanned", "msg": "已扫码，等待确认"})
        elif errcode == "403":
            return JSONResponse(content={"status": "refused", "msg": "用户取消"})
        elif errcode == "402":
            return JSONResponse(content={"status": "expired", "msg": "二维码过期"})
        else:
            return JSONResponse(content={"status": "unknown", "msg": f"未知状态码: {errcode}"})

    except Exception as e:
        logger.error(f"检查状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
