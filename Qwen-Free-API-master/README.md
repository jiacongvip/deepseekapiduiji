# Qwen AI Free 服务

## 项目说明

<span>[ 中文 | <a href="README_EN.md">English</a> ]</span>

本项目由[https://github.com/LLM-Red-Team/qwen-free-api](https://github.com/LLM-Red-Team/qwen-free-api)修改而来,感谢大佬的贡献!
重要提示：原项目由于供应链攻击，提交的代码内包含恶意代码，强烈建议不再继续使用。

修改原因：
1. 原项目中官方接口修改导致回答乱序，API基本不可用
2. 原项目作者基本不咋更新了
3. 已去除原项目中包含的恶意代码，欢迎对本项目源码进行审查

## 更新说明

1. 修改chat.ts 修改非流式输出接口方法，参考原项目issue [返回的消息带错乱](https://github.com/LLM-Red-Team/qwen-free-api/issues/72)

2. 更新models.ts 模型列表，支持qwen3-235b-a22b、qwen3-coder-plus、qwen-plus-latest等最新模型

3. 重新打包新版本的docker镜像，`akashrajpuroh1t/qwen-free-api-fix:latest`

4. 已修复源码中恶意代码问题，并重新打包，验证如下：

- 包含混淆代码在`src/api/chat.js`文件末尾处，构建完容器内为`/app/dist/index.js`文件1871行左右，如下图所示红框部分：
![index.js](./doc/index.js.png)

- 修复后去除混淆代码，构建完容器内为`/app/dist/index.js`文件1951行左右，如下图所示：
![index-fix.js](./doc/index-fix.js.png)

模型已通过测试如下：

![](https://cdn.jsdelivr.net/gh/xiaoY233/PicList@main/public/assets/qwen-free.png)

### 更新日志

- v1.0.1 (2025-12-07)

    - 重构默认首页样式和内容，修复部分描述
    - 新增Gemini和Claude适配器

- v1.0.0-fix (2025-11-23)

    - 修复源码中恶意代码问题,解决构建时报错问题

- v0.0.23.2 （2025-11-09）

    - 修复回答重复问题：优化流式响应处理逻辑，仅当文本长度增加时才提取增量内容，避免重复输出

- v0.0.23.1 （2025-08-12）

    - 修复报错：STRING_IS_BLANK-sessionId不能为空

- v0.0.23 （2025-08-11）

    - 经测试，原版接口实际指定模型ID并未生效，修改chat.ts相关逻辑，支持指定模型ID。
    - 根据官方最新Chat-API接口[https://chat.qwen.ai/api/models](https://chat.qwen.ai/api/models),更新models.ts列表

  
## 免责声明

**逆向API是不稳定的，建议前往阿里云官方 https://dashscope.console.aliyun.com/ 付费使用API，避免封禁的风险。**

**本组织和个人不接受任何资金捐助和交易，此项目是纯粹研究交流学习性质！**

**仅限自用，禁止对外提供服务或商用，避免对官方造成服务压力，否则风险自担！**

**仅限自用，禁止对外提供服务或商用，避免对官方造成服务压力，否则风险自担！**

**仅限自用，禁止对外提供服务或商用，避免对官方造成服务压力，否则风险自担！**

## 效果示例

### 服务默认首页

服务启动后，默认首页添加了接入指南和接口说明，方便快速接入，不用来回切换找文档。

![index.html](./doc/index.png)

### Gemini-cli接入

版本添加了gemini-cli适配器，可以直接在gemini-cli中调用API。

![gemini-cli](./doc/gemini-cli.png)

### Claude-code接入

版本添加了Claude-code适配器，可以直接在Claude-code中调用API。

![claude-code](./doc/claude-code.png)

### 验明正身Demo

![验明正身](./doc/example-1.png)

### 多轮对话Demo

![多轮对话](./doc/example-2.png)

### AI绘图Demo

![AI绘图](./doc/example-3.png)

### 长文档解读Demo

![长文本解读](./doc/example-5.png)

### 图像解析Demo

![图像解析](./doc/example-6.png)

### 10线程并发测试

![10线程并发测试](./doc/example-4.png)

## 接入准备

### 方法1

从 [通义千问](https://tongyi.aliyun.com/qianwen) 登录

进入通义千问随便发起一个对话，然后F12打开开发者工具，从Application > Cookies中找到`tongyi_sso_ticket`的值，这将作为Authorization的Bearer Token值：`Authorization: Bearer TOKEN`

![获取tongyi_sso_ticket](./doc/example-0.png)

### 方法2

从 [阿里云](https://www.aliyun.com/) 登录（如果该账号有服务器等重要资产不建议使用），如果该账号之前未进入过[通义千问](https://tongyi.aliyun.com/qianwen) ，需要先进入同意协议，否则无法生效。

然后F12打开开发者工具，从Application > Cookies中找到`login_aliyunid_ticket`的值，这将作为Authorization的Bearer Token值：`Authorization: Bearer TOKEN`

![获取login_aliyunid_ticket](./doc/example-7.png)

### 多账号接入

你可以通过提供多个账号的`tongyi_sso_ticket`或`login_aliyunid_ticket`，并使用,拼接提供：

`Authorization: Bearer TOKEN1,TOKEN2,TOKEN3`

每次请求服务会从中挑选一个。

## Docker部署

请准备一台具有公网IP的服务器并将8000端口开放。

拉取镜像并启动服务

```shell
docker run -it -d --init --name qwen-free-api-fix -p 8000:8000 -e TZ=Asia/Shanghai akashrajpuroh1t/qwen-free-api-fix:latest
```

查看服务实时日志

```shell
docker logs -f qwen-free-api-fix
```

重启服务

```shell
docker restart qwen-free-api-fix
```

停止服务

```shell
docker stop qwen-free-api-fix
```

### Docker-compose部署

```yaml
version: '3'

services:
  qwen-free-api:
    container_name: qwen-free-api-fix
    image: akashrajpuroh1t/qwen-free-api-fix:latest
    restart: always
    ports:
      - "8000:8000"
    environment:
      - TZ=Asia/Shanghai
```
### 其他部署

其他部署方式，由于未经过测试，所以不再推荐，建议还是Docker部署使用

## 接口列表

目前支持与openai兼容的 `/v1/chat/completions` 接口，可自行使用与openai或其他兼容的客户端接入接口，或者使用 [dify](https://dify.ai/) 等线上服务接入使用。

### 对话补全

对话补全接口，与openai的 [chat-completions-api](https://platform.openai.com/docs/guides/text-generation/chat-completions-api) 兼容。

**POST /v1/chat/completions**

header 需要设置 Authorization 头部：

```
Authorization: Bearer [tongyi_sso_ticket/login_aliyunid_ticket]
```

请求数据：
```json
{
    // 模型名称随意填写
    "model": "qwen",
    // 目前多轮对话基于消息合并实现，某些场景可能导致能力下降且受单轮最大token数限制
    // 如果您想获得原生的多轮对话体验，可以传入上一轮消息获得的id，来接续上下文
    // "conversation_id": "bc9ef150d0e44794ab624df958292300-40811965812e4782bb87f1a9e4e2b2cd",
    "messages": [
        {
            "role": "user",
            "content": "你是谁？"
        }
    ],
    // 如果使用SSE流请设置为true，默认false
    "stream": false
}
```

响应数据：
```json
{
    // 如果想获得原生多轮对话体验，此id，你可以传入到下一轮对话的conversation_id来接续上下文
    "id": "bc9ef150d0e44794ab624df958292300-40811965812e4782bb87f1a9e4e2b2cd",
    "model": "qwen",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "我是阿里云研发的超大规模语言模型，我叫通义千问。"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2
    },
    "created": 1710152062
}
```
