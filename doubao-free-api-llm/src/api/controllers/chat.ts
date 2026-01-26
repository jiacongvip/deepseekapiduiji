import { PassThrough } from "stream";
import crypto from "crypto";
import path from "path";
import fs from "fs-extra";
import _ from "lodash";
import mime from "mime";
import axios, { AxiosRequestConfig, AxiosResponse } from "axios";

import APIException from "@/lib/exceptions/APIException.ts";
import EX from "@/api/consts/exceptions.ts";
import { createParser } from "eventsource-parser";
import logger from "@/lib/logger.ts";
import util from "@/lib/util.ts";

// 模型名称
const MODEL_NAME = "doubao";
// 默认的AgentID
const DEFAULT_ASSISTANT_ID = "497858";
// 版本号
const VERSION_CODE = "20800";
// 设备ID
const DEVICE_ID = Math.random() * 999999999999999999 + 7000000000000000000;
// WebID
const WEB_ID = Math.random() * 999999999999999999 + 7000000000000000000;
// 用户ID
const USER_ID = util.uuid(false);
// 最大重试次数
const MAX_RETRY_COUNT = 3;
// 重试延迟
const RETRY_DELAY = 5000;
// 伪装headers（尽量贴近 Python 版本的最小集合，避免 header 与 UA 不一致触发风控）
const FAKE_HEADERS = {
  Accept: "*/*",
  "Accept-Encoding": "gzip, deflate, br, zstd",
  "Accept-Language": "zh-CN,zh;q=0.9",
  Origin: "https://www.doubao.com",
  Referer: "https://www.doubao.com/chat/",
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
  "Sec-Ch-Ua-Mobile": "?0",
  "Sec-Ch-Ua-Platform": '"Windows"',
};
// 文件最大大小
const FILE_MAX_SIZE = 100 * 1024 * 1024;

type SessionConfig = {
  cookie?: string;
  device_id?: string;
  tea_uuid?: string;
  web_id?: string;
  room_id?: string;
  x_flow_trace?: string;
};
type SessionConfigValue = string | SessionConfig;

const SESSION_CONFIG_FILENAMES = [
  "session-cookies-auto.json",
  "session-cookies.json",
];

let sessionCookiesCache: Record<string, SessionConfigValue> | null = null;

function extractSessionIdFromCookie(cookie: string) {
  const match = cookie.match(/sessionid=([^;]+)/);
  return match ? match[1].trim() : null;
}

function getCookieKeys(cookie: string) {
  if (!cookie) return new Set<string>();
  const keys = cookie
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part.split("=")[0]?.trim())
    .filter(Boolean);
  return new Set(keys);
}

function isSessionIdOnlyCookie(cookie: string) {
  const keys = getCookieKeys(cookie);
  if (!keys.has("sessionid")) return false;
  const allowedKeys = new Set(["sessionid", "sessionid_ss", "msToken"]);
  for (const key of keys) {
    if (!allowedKeys.has(key)) return false;
  }
  return true;
}

function ensureMsToken(cookie: string, msToken: string) {
  if (!cookie) return cookie;
  if (cookie.includes("msToken=")) return cookie;
  return `${cookie}; msToken=${msToken}`;
}

function extractMsTokenFromCookie(cookie: string) {
  const match = cookie.match(/(?:^|;\s*)msToken=([^;]+)/);
  return match ? match[1].trim() : "";
}

function getCookieValue(cookie: string, name: string) {
  if (!cookie) return null;
  const parts = cookie
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean);
  for (const part of parts) {
    const [key, ...rest] = part.split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}

function setCookieValue(cookie: string, name: string, value: string) {
  if (!cookie) return `${name}=${value}`;
  const parts = cookie
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean);
  let found = false;
  const updated = parts.map((part) => {
    const [key] = part.split("=");
    if (key === name) {
      found = true;
      return `${name}=${value}`;
    }
    return part;
  });
  if (!found) updated.push(`${name}=${value}`);
  return updated.join("; ");
}

function patchCookieSessionId(cookie: string, sessionid: string) {
  let patched = cookie;
  patched = setCookieValue(patched, "sessionid", sessionid);
  patched = setCookieValue(patched, "sessionid_ss", sessionid);
  // 不强行改 sid_tt / sid_guard：更贴近“浏览器里只替换 sessionid”的做法，减少字段不一致触发风控
  return patched;
}

function getCookieTemplate() {
  const sessionCookies = loadSessionCookies();
  const templateValue = sessionCookies["__template__"];
  if (templateValue) {
    const cookie =
      typeof templateValue === "string"
        ? templateValue
        : templateValue.cookie;
    if (cookie && !isSessionIdOnlyCookie(cookie)) return cookie;
  }
  for (const value of Object.values(sessionCookies)) {
    const cookie = typeof value === "string" ? value : value?.cookie;
    if (cookie && !isSessionIdOnlyCookie(cookie)) return cookie;
  }
  return null;
}

function getTemplateSessionConfig() {
  const sessionCookies = loadSessionCookies();
  const templateValue = sessionCookies["__template__"];
  const normalize = (value: SessionConfigValue | undefined) => {
    if (!value) return null;
    if (typeof value === "string") return { cookie: value } as SessionConfig;
    return value;
  };
  const fromTemplate = normalize(templateValue);
  if (fromTemplate && fromTemplate.cookie && !isSessionIdOnlyCookie(fromTemplate.cookie))
    return fromTemplate;
  for (const value of Object.values(sessionCookies)) {
    const config = normalize(value);
    if (!config?.cookie) continue;
    if (isSessionIdOnlyCookie(config.cookie)) continue;
    // 优先挑选带有真实参数的模板（device/web/flow/room）
    if (config.device_id || config.web_id || config.tea_uuid || config.room_id || config.x_flow_trace)
      return config;
  }
  // 退化：只要有非 sessionid-only 的 cookie 也可以当模板
  for (const value of Object.values(sessionCookies)) {
    const config = normalize(value);
    if (!config?.cookie) continue;
    if (isSessionIdOnlyCookie(config.cookie)) continue;
    return config;
  }
  return null;
}

function loadSessionCookies() {
  if (sessionCookiesCache !== null) {
    return sessionCookiesCache;
  }
  sessionCookiesCache = {};
  try {
    for (const filename of SESSION_CONFIG_FILENAMES) {
      const configPath = path.join(path.resolve(), filename);
      if (!fs.pathExistsSync(configPath)) continue;
      const rawConfig = fs.readJsonSync(configPath);
      for (const [key, value] of Object.entries(rawConfig)) {
        if (typeof value === "string") {
          const cookie = value;
          const sessionid = extractSessionIdFromCookie(cookie) || key;
          sessionCookiesCache[sessionid] = { cookie };
          if (key !== sessionid) {
            sessionCookiesCache[key] = sessionCookiesCache[sessionid];
          }
          logger.info(
            `Loaded cookie for sessionid: ${sessionid.substring(0, 8)}...`
          );
        } else if (typeof value === "object" && value !== null) {
          sessionCookiesCache[key] = value;
          const cookie = value.cookie;
          const sessionid = cookie ? extractSessionIdFromCookie(cookie) : null;
          if (sessionid && sessionid !== key) {
            sessionCookiesCache[sessionid] = value;
          }
        }
      }
    }
  } catch (err) {
    logger.warn(`Failed to load session cookies config: ${err}`);
    sessionCookiesCache = {};
  }
  return sessionCookiesCache;
}

function buildSidGuard(sessionid: string, timestamp: number, maxAgeSeconds: number) {
  const expireTime = timestamp + maxAgeSeconds;
  const expireDate = new Date(expireTime * 1000).toUTCString();
  const dateParts = expireDate.split(" ");
  const sidGuardDate = dateParts.length >= 6
    ? `${dateParts[0]} ${dateParts[1]}-${dateParts[2]}-${dateParts[3]} ${dateParts[4]} ${dateParts[5]}`
    : expireDate;
  const encodedSidGuardDate = encodeURIComponent(sidGuardDate).replace(/%20/g, "+");
  return `${sessionid}%7C${timestamp}%7C${maxAgeSeconds}%7C${encodedSidGuardDate}`;
}

function generateFullCookieFromSessionId(sessionid: string, msToken: string) {
  const timestamp = util.unixTimestamp();
  const sid_guard = buildSidGuard(sessionid, timestamp, 2592000);
  const uidHash = crypto.createHash("md5").update(sessionid).digest("hex");
  const uid_tt = uidHash;
  const ttcidHash = crypto.createHash("md5").update(sessionid + "ttcid").digest("hex");
  const ttcid = ttcidHash;
  const webIdHash = crypto.createHash("md5").update(sessionid + "webid").digest("hex");
  const s_v_web_id = `verify_${webIdHash.substring(0, 20)}_${webIdHash.substring(20, 32)}`;
  const csrfHash = crypto.createHash("md5").update(sessionid + "csrf").digest("hex");
  const passport_csrf_token = csrfHash;
  const odin_tt = crypto.createHash("sha256").update(sessionid + "odin").digest("hex");
  const ttwidHash1 = crypto.createHash("md5").update(sessionid + "ttwid1").digest("hex");
  const ttwidHash2 = crypto.createHash("md5").update(sessionid + "ttwid2").digest("hex");
  const ttwid = `${ttwidHash1}${ttwidHash2}`.substring(0, 32);
  const session_tlb_tag = util.generateRandomString({ length: 64, charset: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_=" });
  const sid_ucp_v1 = `1.0.0-${util.generateRandomString({ length: 64 })}`;
  const ssid_ucp_v1 = `1.0.0-${util.generateRandomString({ length: 64 })}`;
  return [
    `hook_slardar_session_id=${sessionid}`,
    `i18next=zh`,
    `passport_csrf_token=${passport_csrf_token}`,
    `passport_csrf_token_default=${passport_csrf_token}`,
    `is_staff_user=false`,
    `s_v_web_id=${s_v_web_id}`,
    `ttcid=${ttcid}`,
    `odin_tt=${odin_tt}`,
    `n_mh=${util.generateRandomString({ length: 24 })}`,
    `sid_guard=${sid_guard}`,
    `uid_tt=${uid_tt}`,
    `uid_tt_ss=${uid_tt}`,
    `sid_tt=${sessionid}`,
    `sessionid=${sessionid}`,
    `sessionid_ss=${sessionid}`,
    `session_tlb_tag=${session_tlb_tag}`,
    `sid_ucp_v1=${sid_ucp_v1}`,
    `ssid_ucp_v1=${ssid_ucp_v1}`,
    `ttwid=${ttwid}`,
    `passport_fe_beating_status=true`,
    `msToken=${msToken}`
  ].join("; ");
}

function generateCookie(refreshToken: string, msToken: string) {
  const sessionCookies = loadSessionCookies();
  const sessionConfig = sessionCookies[refreshToken];
  if (sessionConfig && typeof sessionConfig === "object" && sessionConfig.cookie) {
    const configuredCookie = sessionConfig.cookie;
    if (isSessionIdOnlyCookie(configuredCookie)) {
      const sessionid = extractSessionIdFromCookie(configuredCookie) || refreshToken;
      const templateCookie = getCookieTemplate();
      if (templateCookie) return ensureMsToken(patchCookieSessionId(templateCookie, sessionid), msToken);
      return generateFullCookieFromSessionId(sessionid, msToken);
    }
    return ensureMsToken(configuredCookie, msToken);
  }
  if (sessionConfig && typeof sessionConfig === "string") {
    return generateFullCookieFromSessionId(sessionConfig, msToken);
  }
  const templateCookie = getCookieTemplate();
  if (templateCookie) return ensureMsToken(patchCookieSessionId(templateCookie, refreshToken), msToken);
  return generateFullCookieFromSessionId(refreshToken, msToken);
}

function getRoomId(refreshToken: string) {
  const sessionCookies = loadSessionCookies();
  const sessionConfig = sessionCookies[refreshToken];
  if (sessionConfig && typeof sessionConfig === "object" && sessionConfig.room_id) {
    return sessionConfig.room_id;
  }
  const templateConfig = getTemplateSessionConfig();
  if (templateConfig?.room_id) return templateConfig.room_id;
  return null;
}

function getFlowTrace(refreshToken: string) {
  const isValidFlowTrace = (value: string) =>
    /^04-[0-9a-fA-F]{32}-[0-9a-fA-F]{16}-01$/.test(value);
  const sessionCookies = loadSessionCookies();
  const sessionConfig = sessionCookies[refreshToken];
  if (sessionConfig && typeof sessionConfig === "object" && sessionConfig.x_flow_trace) {
    if (isValidFlowTrace(sessionConfig.x_flow_trace)) return sessionConfig.x_flow_trace;
  }
  const templateConfig = getTemplateSessionConfig();
  if (templateConfig?.x_flow_trace && isValidFlowTrace(templateConfig.x_flow_trace))
    return templateConfig.x_flow_trace;
  return `04-${util.uuid(false)}-${util.uuid(false).substring(0, 16)}-01`;
}

function extractFpFromCookie(cookie: string) {
  const match = cookie.match(/(?:^|;\s*)s_v_web_id=([^;]+)/);
  return match ? match[1].trim() : "";
}

function generateDeviceIdFromSessionId(sessionid: string) {
  const hash = crypto.createHash("md5").update(sessionid + "device").digest("hex");
  const numHash = parseInt(hash.substring(0, 15), 16);
  return (7e18 + (numHash % 3e18)).toString();
}

function getDeviceId(refreshToken: string) {
  const sessionCookies = loadSessionCookies();
  const sessionConfig = sessionCookies[refreshToken];
  if (sessionConfig && typeof sessionConfig === "object" && sessionConfig.device_id) {
    return sessionConfig.device_id;
  }
  const templateConfig = getTemplateSessionConfig();
  if (templateConfig?.device_id) return templateConfig.device_id;
  return generateDeviceIdFromSessionId(refreshToken);
}

function generateWebIdFromSessionId(sessionid: string) {
  const hash = crypto.createHash("md5").update(sessionid + "web").digest("hex");
  const numHash = parseInt(hash.substring(0, 15), 16);
  return (7e18 + (numHash % 3e18)).toString();
}

function getWebId(refreshToken: string) {
  const sessionCookies = loadSessionCookies();
  const sessionConfig = sessionCookies[refreshToken];
  if (sessionConfig && typeof sessionConfig === "object") {
    if (sessionConfig.web_id) return sessionConfig.web_id;
    if (sessionConfig.tea_uuid) return sessionConfig.tea_uuid;
  }
  const templateConfig = getTemplateSessionConfig();
  if (templateConfig?.web_id) return templateConfig.web_id;
  if (templateConfig?.tea_uuid) return templateConfig.tea_uuid;
  return generateWebIdFromSessionId(refreshToken);
}

/**
 * 获取缓存中的access_token
 *
 * 目前doubao的access_token是固定的，暂无刷新功能
 *
 * @param refreshToken 用于刷新access_token的refresh_token
 */
async function acquireToken(refreshToken: string): Promise<string> {
  return refreshToken;
}

/**
 * 生成伪msToken
 *
 * 更贴近浏览器里的 msToken 形态：base64url（保留 1 个 '=' padding）
 */
function generateFakeMsToken() {
  // 95 bytes -> base64 长度 128，末尾 1 个 '='
  const bytes = crypto.randomBytes(95);
  return bytes
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

/**
 * 生成伪a_bogus
 */
function generateFakeABogus() {
  return `mf-${util.generateRandomString({
    length: 34,
  })}-${util.generateRandomString({
    length: 6,
  })}`;
}

/**
 * 请求doubao
 *
 * @param method 请求方法
 * @param uri 请求路径
 * @param params 请求参数
 * @param headers 请求头
 */
async function request(method: string, uri: string, refreshToken: string, options: AxiosRequestConfig = {}) {
  const token = await acquireToken(refreshToken);
  let msToken = generateFakeMsToken();
  const cookie = generateCookie(token, msToken);
  const cookieMsToken = extractMsTokenFromCookie(cookie);
  if (cookieMsToken) msToken = cookieMsToken;
  const fp = extractFpFromCookie(cookie);
  const deviceId = getDeviceId(token);
  const webId = getWebId(token);
  const flowTrace = getFlowTrace(token);

  // 处理代理配置
  let proxyConfig: AxiosRequestConfig["proxy"] = false;
  const proxyUrl = process.env.PROXY_URL;
  if (proxyUrl) {
    try {
      const url = new URL(proxyUrl);
      proxyConfig = {
        protocol: url.protocol.replace(":", ""),
        host: url.hostname,
        port: parseInt(url.port) || (url.protocol === "https:" ? 443 : 80),
      };
      if (url.username && url.password) {
        proxyConfig.auth = {
          username: url.username,
          password: url.password,
        };
      }
      logger.info(`Using proxy: ${proxyUrl}`);
    } catch (e) {
      logger.error(`Invalid PROXY_URL: ${proxyUrl}`);
    }
  }

  const response = await axios.request({
    method,
    url: `https://www.doubao.com${uri}`,
    proxy: proxyConfig,
    params: {
      aid: DEFAULT_ASSISTANT_ID,
      device_id: deviceId,
      device_platform: "web",
      language: "zh",
      pc_version: "3.1.2",
      pkg_type: "release_version",
      real_aid: DEFAULT_ASSISTANT_ID,
      region: "CN",
      samantha_web: 1,
      sys_region: "CN",
      tea_uuid: webId,
      "use-olympus-account": 1,
      version_code: VERSION_CODE,
      web_id: webId,
      ...(fp ? { fp } : {}),
      ...(options.params || {})
    },
    headers: {
      ...FAKE_HEADERS,
      Cookie: cookie,
      "x-flow-trace": flowTrace,
      ...(options.headers || {}),
    },
    timeout: 15000,
    validateStatus: () => true,
    ..._.omit(options, "params", "headers"),
  });
  // 流式响应直接返回response
  if (options.responseType == "stream")
    return response;
  return checkResult(response);
}

/**
 * 移除会话
 *
 * 在对话流传输完毕后移除会话，避免创建的会话出现在用户的对话列表中
 *
 * @param refreshToken 用于刷新access_token的refresh_token
 */
async function removeConversation(
  convId: string,
  refreshToken: string
) {
  await request("post", "/samantha/thread/delete", refreshToken, {
    data: {
      conversation_id: convId
    }
  });
}

/**
 * 同步对话补全
 *
 * @param messages 参考gpt系列消息格式，多轮对话请完整提供上下文
 * @param refreshToken 用于刷新access_token的refresh_token
 * @param assistantId 智能体ID，默认使用Doubao原版
 * @param retryCount 重试次数
 */
async function createCompletion(
  messages: any[],
  refreshToken: string,
  assistantId = DEFAULT_ASSISTANT_ID,
  refConvId = "",
  retryCount = 0
) {
  return (async () => {
    logger.info(messages);

    // 提取引用文件URL并上传获得引用的文件ID列表
    const refFileUrls = extractRefFileUrls(messages);
    const refs = refFileUrls.length
      ? await Promise.all(
        refFileUrls.map((fileUrl) => uploadFile(fileUrl, refreshToken))
      )
      : [];

    // 如果引用对话ID不正确则重置引用
    if (!/[0-9a-zA-Z]{24}/.test(refConvId)) refConvId = "";

    // 请求流
    const response = await request("post", "/samantha/chat/completion", refreshToken, {
      data: {
        messages: messagesPrepare(messages, refs, !!refConvId),
        completion_option: {
          is_regen: false,
          with_suggest: true,
          need_create_conversation: true,
          launch_stage: 1,
          is_replace: false,
          is_delete: false,
          message_from: 0,
          event_id: "0"
        },
        conversation_id: "0",
        local_conversation_id: `local_16${util.generateRandomString({ length: 14, charset: "numeric" })}`,
        local_message_id: util.uuid()
      },
      headers: {
        Referer: getRoomId(refreshToken)
          ? `https://www.doubao.com/chat/${getRoomId(refreshToken)}`
          : "https://www.doubao.com/chat/",
        "Agw-js-conv": "str",
        Accept: "text/event-stream",
      },
      // 300秒超时
      timeout: 300000,
      responseType: "stream"
    });
    if (response.headers["content-type"].indexOf("text/event-stream") == -1) {
      response.data.on("data", (buffer) => logger.error(buffer.toString()));
      throw new APIException(
        EX.API_REQUEST_FAILED,
        `Stream response Content-Type invalid: ${response.headers["content-type"]}`
      );
    }

    const streamStartTime = util.timestamp();
    // 接收流为输出文本
    const answer = await receiveStream(response.data);
    logger.success(
      `Stream has completed transfer ${util.timestamp() - streamStartTime}ms`
    );

    // 异步移除会话
    removeConversation(answer.id, refreshToken).catch(
      (err) => !refConvId && console.error('移除会话失败：', err)
    );

    return answer;
  })().catch((err) => {
    if (retryCount < MAX_RETRY_COUNT) {
      logger.error(`Stream response error: ${err.stack}`);
      logger.warn(`Try again after ${RETRY_DELAY / 1000}s...`);
      return (async () => {
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY));
        return createCompletion(
          messages,
          refreshToken,
          assistantId,
          refConvId,
          retryCount + 1
        );
      })();
    }
    throw err;
  });
}

/**
 * 流式对话补全
 *
 * @param messages 参考gpt系列消息格式，多轮对话请完整提供上下文
 * @param refreshToken 用于刷新access_token的refresh_token
 * @param assistantId 智能体ID，默认使用Doubao原版
 * @param retryCount 重试次数
 */
async function createCompletionStream(
  messages: any[],
  refreshToken: string,
  assistantId = DEFAULT_ASSISTANT_ID,
  refConvId = "",
  retryCount = 0
) {
  return (async () => {
    logger.info(messages);

    // 提取引用文件URL并上传获得引用的文件ID列表
    const refFileUrls = extractRefFileUrls(messages);
    const refs = refFileUrls.length
      ? await Promise.all(
        refFileUrls.map((fileUrl) => uploadFile(fileUrl, refreshToken))
      )
      : [];

    // 如果引用对话ID不正确则重置引用
    if (!/[0-9a-zA-Z]{24}/.test(refConvId)) refConvId = "";

    // 请求流
    const response = await request("post", "/samantha/chat/completion", refreshToken, {
      data: {
        messages: messagesPrepare(messages, refs, !!refConvId),
        completion_option: {
          is_regen: false,
          with_suggest: true,
          need_create_conversation: true,
          launch_stage: 1,
          is_replace: false,
          is_delete: false,
          message_from: 0,
          event_id: "0"
        },
        conversation_id: "0",
        local_conversation_id: `local_16${util.generateRandomString({ length: 14, charset: "numeric" })}`,
        local_message_id: util.uuid()
      },
      headers: {
        Referer: getRoomId(refreshToken)
          ? `https://www.doubao.com/chat/${getRoomId(refreshToken)}`
          : "https://www.doubao.com/chat/",
        "Agw-js-conv": "str",
        Accept: "text/event-stream",
      },
      // 300秒超时
      timeout: 300000,
      responseType: "stream"
    });
    
    // Debug log for headers
    // 注意：这里的 cookie 变量需要在 createCompletionStream 作用域内获取，或者从上一步 request 中传递出来
    // 由于 request 内部封装了 cookie 生成逻辑，这里直接拿不到 cookie 变量。
    // 为了调试，我们简单打印一下提示信息，或者需要修改 request 函数返回 cookie
    logger.info(`Sending request to Doubao...`);

    if (response.headers["content-type"].indexOf("text/event-stream") == -1) {
      logger.error(
        `Invalid response Content-Type:`,
        response.headers["content-type"]
      );
      // Log full response body for debugging error
      response.data.on("data", (buffer) => {
          const str = buffer.toString();
          logger.error(`Response Body Preview: ${str.substring(0, 500)}`);
      });
      const transStream = new PassThrough();
      transStream.end(
        `data: ${JSON.stringify({
          id: "",
          model: MODEL_NAME,
          object: "chat.completion.chunk",
          choices: [
            {
              index: 0,
              delta: {
                role: "assistant",
                content: "服务暂时不可用，第三方响应错误",
              },
              finish_reason: "stop",
            },
          ],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
          created: util.unixTimestamp(),
        })}\n\n`
      );
      return transStream;
    }

    const streamStartTime = util.timestamp();
    // 创建转换流将消息格式转换为gpt兼容格式
    return createTransStream(response.data, (convId: string) => {
      logger.success(
        `Stream has completed transfer ${util.timestamp() - streamStartTime}ms`
      );
      // 流传输结束后异步移除会话
      removeConversation(convId, refreshToken).catch(
        (err) => !refConvId && console.error(err)
      );
    });
  })().catch((err) => {
    if (retryCount < MAX_RETRY_COUNT) {
      logger.error(`Stream response error: ${err.stack}`);
      logger.warn(`Try again after ${RETRY_DELAY / 1000}s...`);
      return (async () => {
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY));
        return createCompletionStream(
          messages,
          refreshToken,
          assistantId,
          refConvId,
          retryCount + 1
        );
      })();
    }
    throw err;
  });
}

/**
 * 提取消息中引用的文件URL
 *
 * @param messages 参考gpt系列消息格式，多轮对话请完整提供上下文
 */
function extractRefFileUrls(messages: any[]) {
  const urls = [];
  // 如果没有消息，则返回[]
  if (!messages.length) {
    return urls;
  }
  // 只获取最新的消息
  const lastMessage = messages[messages.length - 1];
  if (_.isArray(lastMessage.content)) {
    lastMessage.content.forEach((v) => {
      if (!_.isObject(v) || !["file", "image_url"].includes(v["type"])) return;
      // doubao-free-api支持格式
      if (
        v["type"] == "file" &&
        _.isObject(v["file_url"]) &&
        _.isString(v["file_url"]["url"])
      )
        urls.push(v["file_url"]["url"]);
      // 兼容gpt-4-vision-preview API格式
      else if (
        v["type"] == "image_url" &&
        _.isObject(v["image_url"]) &&
        _.isString(v["image_url"]["url"])
      )
        urls.push(v["image_url"]["url"]);
    });
  }
  logger.info("本次请求上传：" + urls.length + "个文件");
  return urls;
}

/**
 * 消息预处理
 *
 * 由于接口只取第一条消息，此处会将多条消息合并为一条，实现多轮对话效果
 *
 * @param messages 参考gpt系列消息格式，多轮对话请完整提供上下文
 * @param refs 参考文件列表
 * @param isRefConv 是否为引用会话
 */
function messagesPrepare(messages: any[], refs: any[], isRefConv = false) {
  let content;
  if (isRefConv || messages.length < 2) {
    content = messages.reduce((content, message) => {
      if (_.isArray(message.content)) {
        return message.content.reduce((_content, v) => {
          if (!_.isObject(v) || v["type"] != "text") return _content;
          return _content + (v["text"] || "") + "\n";
        }, content);
      }
      return content + `${message.content}\n`;
    }, "");
    logger.info("\n透传内容：\n" + content);
  } else {
    // 检查最新消息是否含有"type": "image_url"或"type": "file",如果有则注入消息
    let latestMessage = messages[messages.length - 1];
    let hasFileOrImage =
      Array.isArray(latestMessage.content) &&
      latestMessage.content.some(
        (v) =>
          typeof v === "object" && ["file", "image_url"].includes(v["type"])
      );
    if (hasFileOrImage) {
      let newFileMessage = {
        content: "关注用户最新发送文件和消息",
        role: "system",
      };
      messages.splice(messages.length - 1, 0, newFileMessage);
      logger.info("注入提升尾部文件注意力system prompt");
    } else {
      // 由于注入会导致设定污染，暂时注释
      // let newTextMessage = {
      //   content: "关注用户最新的消息",
      //   role: "system",
      // };
      // messages.splice(messages.length - 1, 0, newTextMessage);
      // logger.info("注入提升尾部消息注意力system prompt");
    }
    content = (
      messages.reduce((content, message) => {
        const role = message.role
          .replace("system", "<|im_start|>system")
          .replace("assistant", "<|im_start|>assistant")
          .replace("user", "<|im_start|>user");
        if (_.isArray(message.content)) {
          return message.content.reduce((_content, v) => {
            if (!_.isObject(v) || v["type"] != "text") return _content;
            return _content + (`${role}\n` + v["text"] || "") + "\n";
          }, content);
        }
        return (content += `${role}\n${message.content}\n`) + '<|im_end|>\n';
      }, "")
    )
      // 移除MD图像URL避免幻觉
      .replace(/\!\[.+\]\(.+\)/g, "")
      // 移除临时路径避免在新会话引发幻觉
      .replace(/\/mnt\/data\/.+/g, "");
    logger.info("\n对话合并：\n" + content);
  }

  const fileRefs = refs.filter((ref) => !ref.width && !ref.height);
  const imageRefs = refs
    .filter((ref) => ref.width || ref.height)
    .map((ref) => {
      ref.image_url = ref.file_url;
      return ref;
    });
  return [
    {
      content: JSON.stringify({ text: content }),
      content_type: 2001,
      attachments: [],
      references: [],
    },
  ];
}

/**
 * 预检查文件URL有效性
 *
 * @param fileUrl 文件URL
 */
async function checkFileUrl(fileUrl: string) {
  if (util.isBASE64Data(fileUrl)) return;
  const result = await axios.head(fileUrl, {
    timeout: 15000,
    validateStatus: () => true,
  });
  if (result.status >= 400)
    throw new APIException(
      EX.API_FILE_URL_INVALID,
      `File ${fileUrl} is not valid: [${result.status}] ${result.statusText}`
    );
  // 检查文件大小
  if (result.headers && result.headers["content-length"]) {
    const fileSize = parseInt(result.headers["content-length"], 10);
    if (fileSize > FILE_MAX_SIZE)
      throw new APIException(
        EX.API_FILE_EXECEEDS_SIZE,
        `File ${fileUrl} is not valid`
      );
  }
}

/**
 * 上传文件
 *
 * @param fileUrl 文件URL
 * @param refreshToken 用于刷新access_token的refresh_token
 * @param isVideoImage 是否是用于视频图像
 */
async function uploadFile(
  fileUrl: string,
  refreshToken: string,
  isVideoImage: boolean = false
) {
  // 预检查远程文件URL可用性
  await checkFileUrl(fileUrl);

  let filename, fileData, mimeType;
  // 如果是BASE64数据则直接转换为Buffer
  if (util.isBASE64Data(fileUrl)) {
    mimeType = util.extractBASE64DataFormat(fileUrl);
    const ext = mime.getExtension(mimeType);
    filename = `${util.uuid()}.${ext}`;
    fileData = Buffer.from(util.removeBASE64DataHeader(fileUrl), "base64");
  }
  // 下载文件到内存，如果您的服务器内存很小，建议考虑改造为流直传到下一个接口上，避免停留占用内存
  else {
    filename = path.basename(fileUrl);
    ({ data: fileData } = await axios.get(fileUrl, {
      responseType: "arraybuffer",
      // 100M限制
      maxContentLength: FILE_MAX_SIZE,
      // 60秒超时
      timeout: 60000,
    }));
  }

  // 获取文件的MIME类型
  mimeType = mimeType || mime.getType(filename);


  // 待开发
}

/**
 * 检查请求结果
 *
 * @param result 结果
 */
function checkResult(result: AxiosResponse) {
  if (!result.data) return null;
  const { code, msg, data } = result.data;
  if (!_.isFinite(code)) return result.data;
  if (code === 0) return data;
  throw new APIException(EX.API_REQUEST_FAILED, `[请求doubao失败]: ${msg}`);
}

/**
 * 提取引用网址
 *
 * @param eventData SSE事件数据
 */
function extractReferences(eventData: any) {
  const references: any[] = [];
  try {
    const addReferenceFromTextCard = (textCard: any) => {
      if (!textCard || typeof textCard !== "object") return;
      const url = textCard.url || "";
      if (!url) return;
      const index = !_.isUndefined(textCard.index)
        ? textCard.index
        : textCard.original_doc_rank;
      const refData = {
        title: textCard.title || "",
        url,
        snippet: textCard.summary || "",
        index,
        sitename: textCard.sitename || "",
        publish_time: textCard.publish_time_second || "",
      };
      if (!references.some((r) => r.url === refData.url)) {
        references.push(refData);
        logger.debug(`提取引用: ${refData.title.substring(0, 30)}...`);
      }
    };
    const extractFromSearchResult = (searchResult: any) => {
      if (!searchResult || typeof searchResult !== "object") return;
      const results = Array.isArray(searchResult.results)
        ? searchResult.results
        : [];
      results.forEach((result) => {
        addReferenceFromTextCard(result?.text_card);
      });
      if (results.length > 0) {
        const summary = searchResult.summary || "";
        const queries = Array.isArray(searchResult.queries)
          ? searchResult.queries
          : [];
        logger.info(
          `搜索引用: ${summary}, 关键词: ${queries.join(", ")}`
        );
      }
    };
    const patchOps = Array.isArray(eventData.patch_op)
      ? eventData.patch_op
      : [];
    for (const patchOp of patchOps) {
      if (patchOp.patch_type === 1) {
        const contentBlocks = (
          patchOp.patch_value?.content_block || []
        );
        for (const block of contentBlocks) {
          if (block.block_type === 10025) {
            const content = block.content || {};
            extractFromSearchResult(content.search_query_result_block || {});
          }
        }
      }
    }
    const message = eventData.message;
    if (message) {
      try {
        let contentData: any;
        if (typeof message.content === "string") {
          contentData = JSON.parse(message.content);
        } else if (_.isObject(message.content)) {
          contentData = message.content;
        }
        if (contentData && _.isObject(contentData)) {
          const searchRefs = Array.isArray(contentData.search_references)
            ? contentData.search_references
            : [];
          for (const refItem of searchRefs) {
            const textCard = refItem?.text_card;
            if (textCard) addReferenceFromTextCard(textCard);
          }
          if (message.content_type === 10025) {
            extractFromSearchResult(contentData);
          }
        }
      } catch (err) {
        // ignore parse errors
      }
      const contentBlocks = Array.isArray(message.content_block)
        ? message.content_block
        : [];
      for (const block of contentBlocks) {
        if (block.block_type === 10025) {
          const content = block.content || {};
          extractFromSearchResult(content.search_query_result_block || {});
        }
      }
    }
  } catch (err: any) {
    logger.warn(`提取引用网址时出错: ${err.message || err}`);
  }
  return references;
}

function safeStringify(value: any, length = 200) {
  try {
    const content = JSON.stringify(value);
    if (!content) return "";
    return content.substring(0, length);
  } catch {
    return "";
  }
}

/**
 * 从流接收完整的消息内容
 *
 * @param stream 消息流
 */
async function receiveStream(stream: any): Promise<any> {
  return new Promise((resolve, reject) => {
    const data = {
      id: "",
      model: MODEL_NAME,
      object: "chat.completion",
      choices: [
        {
          index: 0,
          message: { role: "assistant", content: "" },
          finish_reason: "stop",
        },
      ],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      created: util.unixTimestamp(),
    };
    const allReferences: any[] = [];
    let isEnd = false;
    const parser = createParser((event) => {
      try {
        if (event.type !== "event" || isEnd) return;
        const rawResult = _.attempt(() => JSON.parse(event.data));
        if (_.isError(rawResult))
          throw new Error(`Stream response invalid: ${event.data}`);
        logger.debug(
          `SSE Event: event_type=${rawResult.event_type}, has_event_data=${!!rawResult.event_data}`
        );
        if (rawResult.code)
          throw new APIException(
            EX.API_REQUEST_FAILED,
            `[请求doubao失败]: ${rawResult.code}-${rawResult.message}`
          );
        if (rawResult.event_type == 2002) {
          const startResult = _.attempt(() => JSON.parse(rawResult.event_data));
          if (!_.isError(startResult) && startResult.conversation_id) {
            data.id = startResult.conversation_id;
          }
          return;
        }
        if (rawResult.event_type == 2003) {
          isEnd = true;
          logger.debug(
            `Stream ended (2003), content length: ${data.choices[0].message.content.length}, references: ${allReferences.length}`
          );
          data.choices[0].message.content = data.choices[0].message.content.replace(/\n$/, "");
          if (allReferences.length > 0)
            data.choices[0].message.references = allReferences;
          return resolve(data);
        }
        if (rawResult.event_type == 2005) {
          const errorResult = _.attempt(() => JSON.parse(rawResult.event_data));
          if (!_.isError(errorResult) && errorResult.code) {
            const errorMsg =
              errorResult.error_detail?.message ||
              errorResult.message ||
              "未知错误";
            logger.warn(
              `豆包服务器返回错误 (2005): ${errorMsg} (code: ${errorResult.code})`
            );
            throw new APIException(
              EX.API_REQUEST_FAILED,
              `[请求doubao失败]: ${errorMsg} (code: ${errorResult.code})`
            );
          }
          return;
        }
        if (rawResult.event_type != 2001) {
          logger.debug(`Skipping event_type: ${rawResult.event_type}`);
          return;
        }
        const result = _.attempt(() => JSON.parse(rawResult.event_data));
        if (_.isError(result))
          throw new Error(`Stream response invalid: ${rawResult.event_data}`);
        const references = extractReferences(result);
        if (references.length > 0) {
          references.forEach((ref) => {
            if (!allReferences.some((r) => r.url === ref.url)) {
              allReferences.push(ref);
            }
          });
          logger.info(
            `发现 ${references.length} 个新引用，总计 ${allReferences.length} 个引用`
          );
        }
        if (result.is_finish) {
          isEnd = true;
          logger.debug(
            `Stream finished, content length: ${data.choices[0].message.content.length}, references: ${allReferences.length}`
          );
          data.choices[0].message.content = data.choices[0].message.content.replace(/\n$/, "");
          if (allReferences.length > 0)
            data.choices[0].message.references = allReferences;
          return resolve(data);
        }
        if (!data.id && result.conversation_id)
          data.id = result.conversation_id;
        const message = result.message;
        if (!message) {
          logger.debug(
            `No message in result: ${safeStringify(result, 200)}`
          );
          return;
        }
        if (![10000, 2001, 2008].includes(message.content_type)) {
          logger.debug(`Unsupported content_type: ${message.content_type}`);
          return;
        }
        let contentText = "";
        try {
          let contentData: any;
          if (typeof message.content === "string") {
            contentData = JSON.parse(message.content);
          } else {
            contentData = message.content;
          }
          contentText = contentData?.text || "";
          if (contentText) {
            logger.debug(
              `Extracted text: ${contentText.substring(0, 50)}... (长度: ${contentText.length})`
            );
            data.choices[0].message.content += contentText;
          } else {
            logger.debug(
              `No text in content: ${safeStringify(contentData, 200)}`
            );
          }
        } catch (err: any) {
          logger.warn(
            `解析 message.content 失败: ${err.message}, content: ${String(
              message.content
            ).substring(0, 100)}`
          );
        }
      } catch (err) {
        logger.error(err);
        reject(err);
      }
    });
    stream.on("data", (buffer) => parser.feed(buffer.toString()));
    stream.once("error", (err) => reject(err));
    stream.once("close", () => resolve(data));
  });
}

/**
 * 创建转换流
 *
 * 将流格式转换为gpt兼容流格式
 *
 * @param stream 消息流
 * @param endCallback 传输结束回调
 */
function createTransStream(stream: any, endCallback?: Function) {
  let isEnd = false;
  let convId = "";
  const streamReferences: any[] = [];
  const created = util.unixTimestamp();
  const transStream = new PassThrough();
  const safeEndDone = () => {
    if (isEnd) return;
    isEnd = true;
    !transStream.closed && transStream.end("data: [DONE]\n\n");
  };
  const endWithError = (message: string) => {
    if (isEnd) return;
    isEnd = true;
    const content = message ? `❌ ${message}` : "❌ 请求失败";
    // 先输出错误文本，再输出 stop + DONE，确保前端能看到
    !transStream.closed &&
      transStream.write(
        `data: ${JSON.stringify({
          id: convId,
          model: MODEL_NAME,
          object: "chat.completion.chunk",
          choices: [
            {
              index: 0,
              delta: { role: "assistant", content },
              finish_reason: null,
            },
          ],
          created,
        })}\n\n`
      );
    const finalChunk: any = {
      id: convId,
      model: MODEL_NAME,
      object: "chat.completion.chunk",
      choices: [
        {
          index: 0,
          delta: { role: "assistant", content: "" },
          finish_reason: "stop",
        },
      ],
      created,
    };
    if (streamReferences.length > 0) {
      finalChunk.choices[0].delta.references = streamReferences;
    }
    !transStream.closed && transStream.write(`data: ${JSON.stringify(finalChunk)}\n\n`);
    !transStream.closed && transStream.end("data: [DONE]\n\n");
  };
  !transStream.closed &&
    transStream.write(
      `data: ${JSON.stringify({
        id: convId,
        model: MODEL_NAME,
        object: "chat.completion.chunk",
        choices: [
          {
            index: 0,
            delta: { role: "assistant", content: "" },
            finish_reason: null,
          },
        ],
        created,
      })}\n\n`
    );
  const parser = createParser((event) => {
    try {
      if (event.type !== "event" || isEnd) return;
      const rawEventSnapshot = event.data
        ? String(event.data).substring(0, 200)
        : "";
      logger.debug(`原始SSE事件: ${rawEventSnapshot}...`);
      const rawResult = _.attempt(() => JSON.parse(event.data));
      if (_.isError(rawResult))
        throw new Error(`Stream response invalid: ${event.data}`);
      logger.debug(
        `解析后: event_type=${rawResult.event_type}, has_event_data=${!!rawResult.event_data}`
      );
      if (rawResult.code) {
        endWithError(`${rawResult.code}-${rawResult.message}`);
        return;
      }
      if (rawResult.event_type === 2002) {
        const startResult = _.attempt(() => JSON.parse(rawResult.event_data));
        if (!_.isError(startResult) && startResult.conversation_id && !convId) {
          convId = startResult.conversation_id;
        }
        return;
      }
      if (rawResult.event_type === 2003) {
        isEnd = true;
        const finalChunk: any = {
          id: convId,
          model: MODEL_NAME,
          object: "chat.completion.chunk",
          choices: [
            {
              index: 0,
              delta: { role: "assistant", content: "" },
              finish_reason: "stop",
            },
          ],
          created,
        };
        if (streamReferences.length > 0) {
          finalChunk.choices[0].delta.references = streamReferences;
        }
        transStream.write(`data: ${JSON.stringify(finalChunk)}\n\n`);
        !transStream.closed && transStream.end("data: [DONE]\n\n");
        if (convId) endCallback && endCallback(convId);
        return;
      }
      if (rawResult.event_type === 2005) {
        const errorResult = _.attempt(() => JSON.parse(rawResult.event_data));
        if (!_.isError(errorResult) && errorResult.code) {
          const errorMsg =
            errorResult.error_detail?.message || errorResult.message || "未知错误";
          logger.warn(
            `豆包服务器返回错误 (2005): ${errorMsg} (code: ${errorResult.code})`
          );
          endWithError(`${errorMsg} (code: ${errorResult.code})`);
          return;
        }
        return;
      }
      if (rawResult.event_type != 2001) {
        logger.debug(`跳过非2001事件: event_type=${rawResult.event_type}`);
        return;
      }
      const result = _.attempt(() => JSON.parse(rawResult.event_data));
      if (_.isError(result))
        throw new Error(`Stream response invalid: ${rawResult.event_data}`);
      if (!convId) convId = result.conversation_id;
      logger.info(
        `处理事件: is_finish=${result.is_finish}, has_message=${!!result.message}`
      );
      const references = extractReferences(result);
      if (references.length > 0) {
        references.forEach((ref) => {
          if (!streamReferences.some((r) => r.url === ref.url)) {
            streamReferences.push(ref);
          }
        });
        logger.debug(
          `流式响应中发现 ${references.length} 个新引用，总计 ${streamReferences.length} 个引用`
        );
      }
      if (result.is_finish) {
        logger.debug("收到 is_finish=true，准备结束流");
        isEnd = true;
        const finalChunk: any = {
          id: convId,
          model: MODEL_NAME,
          object: "chat.completion.chunk",
          choices: [
            {
              index: 0,
              delta: { role: "assistant", content: "" },
              finish_reason: "stop",
            },
          ],
          created,
        };
        if (streamReferences.length > 0) {
          finalChunk.choices[0].delta.references = streamReferences;
        }
        transStream.write(`data: ${JSON.stringify(finalChunk)}\n\n`);
        !transStream.closed && transStream.end("data: [DONE]\n\n");
        if (convId) endCallback && endCallback(convId);
        return;
      }
      const message = result.message;
      if (!message) {
        logger.debug("Result中没有message字段");
        return;
      }
      if (![10000, 2001, 2008].includes(message.content_type)) {
        logger.debug(`跳过content_type=${message.content_type}`);
        return;
      }
      let contentText = "";
      try {
        let contentData: any;
        if (typeof message.content === "string") {
          try {
            contentData = JSON.parse(message.content);
          } catch (err) {
            logger.warn(
              `解析 content 字符串失败，尝试直接使用原始值: ${String(
                message.content
              ).substring(0, 100)}`
            );
            contentData = { text: message.content };
          }
        } else {
          contentData = message.content;
        }
        contentText = contentData?.text || "";
        if (contentText) {
          logger.info(
            `✅ 提取文本成功: ${contentText.substring(0, 50)}... (长度: ${contentText.length})`
          );
        } else {
        logger.debug(
          `⚠️ 文本为空: ${safeStringify(contentData, 300)}`
        );
        }
      } catch (err: any) {
        logger.error(
          `解析 message.content 失败: ${err.message}, content: ${String(
            message.content
          ).substring(0, 200)}`
        );
        return;
      }
      if (contentText) {
        transStream.write(
          `data: ${JSON.stringify({
            id: convId,
            model: MODEL_NAME,
            object: "chat.completion.chunk",
            choices: [
              {
                index: 0,
                delta: { role: "assistant", content: contentText },
                finish_reason: null,
              },
            ],
            created,
          })}\n\n`
        );
      }
    } catch (err) {
      logger.error(err);
      endWithError((err as any)?.message || "系统错误");
    }
  });
  stream.on("data", (buffer) => parser.feed(buffer.toString()));
  stream.once("error", () => safeEndDone());
  stream.once("close", () => safeEndDone());
  return transStream;
}

/**
 * Token切分
 *
 * @param authorization 认证字符串
 */
function tokenSplit(authorization: string) {
  return authorization.replace("Bearer ", "").split(",");
}

/**
 * 获取Token存活状态
 */
async function getTokenLiveStatus(refreshToken: string) {
  const result = await request("POST", "/passport/account/info/v2", refreshToken, {
    params: {
      account_sdk_source: "web"
    }
  });
  try {
    const { user_id } = checkResult(result);
    return !!user_id;
  } catch (err) {
    return false;
  }
}

export default {
  createCompletion,
  createCompletionStream,
  getTokenLiveStatus,
  tokenSplit,
};
