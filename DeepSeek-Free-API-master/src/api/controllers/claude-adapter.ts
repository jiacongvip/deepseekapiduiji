import { PassThrough } from "stream";
import _ from "lodash";
import chat from "@/api/controllers/chat.ts";
import util from "@/lib/util.ts";
import logger from "@/lib/logger.ts";

const MODEL_NAME = "deepseek-chat";

/**
 * Convert Claude messages format to DeepSeek format
 * 
 * @param messages Claude messages array
 * @param system Optional system message (string or array format)
 */
export function convertClaudeToDeepSeek(messages: any[], system?: string | any[]): any[] {
    const deepseekMessages: any[] = [];

    // Convert system to string if it's an array
    let systemText: string | undefined = undefined;
    if (system) {
        if (Array.isArray(system)) {
            // Extract text from array format system message
            systemText = system
                .filter((item: any) => item.type === "text")
                .map((item: any) => item.text)
                .join("\n");
        } else if (typeof system === "string") {
            systemText = system;
        }
    }

    // If there's a system message, prepend it to the first user message
    let systemPrepended = false;

    for (const msg of messages) {
        if (msg.role === "user") {
            let content = msg.content;

            // Ensure content is defined, default to empty string if undefined/null
            if (content === undefined || content === null) {
                content = "";
            }
            // Handle content array format
            else if (Array.isArray(content)) {
                content = content
                    .filter((item: any) => item.type === "text")
                    .map((item: any) => item.text)
                    .join("\n");
            }

            // Prepend system message to first user message
            if (systemText && !systemPrepended) {
                content = `${systemText}\n\n${content}`;
                systemPrepended = true;
            }

            deepseekMessages.push({
                role: "user",
                content: content
            });
        } else if (msg.role === "assistant") {
            let content = msg.content;

            // Ensure content is defined, default to empty string if undefined/null
            if (content === undefined || content === null) {
                content = "";
            }
            // Handle content array format
            else if (Array.isArray(content)) {
                content = content
                    .filter((item: any) => item.type === "text")
                    .map((item: any) => item.text)
                    .join("\n");
            }

            deepseekMessages.push({
                role: "assistant",
                content: content
            });
        }
    }

    return deepseekMessages;
}

/**
 * Convert DeepSeek response to Claude format
 * 
 * @param deepseekResponse DeepSeek response object
 */
export function convertDeepSeekToClaude(deepseekResponse: any): any {
    const content = deepseekResponse.choices[0].message.content;
    const reasoningContent = deepseekResponse.choices[0].message.reasoning_content || "";

    // Combine reasoning and content if reasoning exists
    const fullContent = reasoningContent
        ? `${reasoningContent}\n\n${content}`
        : content;

    return {
        id: deepseekResponse.id || util.uuid(),
        type: "message",
        role: "assistant",
        content: [
            {
                type: "text",
                text: fullContent
            }
        ],
        model: MODEL_NAME,
        stop_reason: deepseekResponse.choices[0].finish_reason === "stop" ? "end_turn" : "max_tokens",
        stop_sequence: null,
        usage: {
            input_tokens: deepseekResponse.usage?.prompt_tokens || 0,
            output_tokens: deepseekResponse.usage?.completion_tokens || 0
        }
    };
}

/**
 * Convert DeepSeek stream to Claude SSE format
 * 
 * @param deepseekStream DeepSeek stream
 */
export function convertDeepSeekStreamToClaude(deepseekStream: any): PassThrough {
    const transStream = new PassThrough();
    const messageId = util.uuid();
    let contentBuffer = "";
    let reasoningBuffer = "";
    let isFirstChunk = true;

    deepseekStream.on("data", (chunk: Buffer) => {
        const lines = chunk.toString().split("\n");

        for (const line of lines) {
            if (!line.trim() || line.trim() === "data: [DONE]") continue;

            if (line.startsWith("data: ")) {
                try {
                    const data = JSON.parse(line.slice(6));

                    if (data.choices && data.choices[0]) {
                        const delta = data.choices[0].delta;

                        // Send message_start event on first chunk
                        if (isFirstChunk) {
                            transStream.write(`event: message_start\ndata: ${JSON.stringify({
                                type: "message_start",
                                message: {
                                    id: messageId,
                                    type: "message",
                                    role: "assistant",
                                    content: [],
                                    model: MODEL_NAME,
                                    stop_reason: null,
                                    stop_sequence: null,
                                    usage: { input_tokens: 0, output_tokens: 0 }
                                }
                            })}\n\n`);

                            transStream.write(`event: content_block_start\ndata: ${JSON.stringify({
                                type: "content_block_start",
                                index: 0,
                                content_block: { type: "text", text: "" }
                            })}\n\n`);

                            isFirstChunk = false;
                        }

                        // Handle content delta
                        if (delta.content) {
                            contentBuffer += delta.content;
                            transStream.write(`event: content_block_delta\ndata: ${JSON.stringify({
                                type: "content_block_delta",
                                index: 0,
                                delta: { type: "text_delta", text: delta.content }
                            })}\n\n`);
                        }

                        // Handle reasoning content delta
                        if (delta.reasoning_content) {
                            reasoningBuffer += delta.reasoning_content;
                            transStream.write(`event: content_block_delta\ndata: ${JSON.stringify({
                                type: "content_block_delta",
                                index: 0,
                                delta: { type: "text_delta", text: delta.reasoning_content }
                            })}\n\n`);
                        }

                        // Handle finish
                        if (data.choices[0].finish_reason) {
                            transStream.write(`event: content_block_stop\ndata: ${JSON.stringify({
                                type: "content_block_stop",
                                index: 0
                            })}\n\n`);

                            transStream.write(`event: message_delta\ndata: ${JSON.stringify({
                                type: "message_delta",
                                delta: { stop_reason: "end_turn", stop_sequence: null },
                                usage: { output_tokens: 1 }
                            })}\n\n`);

                            transStream.write(`event: message_stop\ndata: ${JSON.stringify({
                                type: "message_stop"
                            })}\n\n`);

                            transStream.end();
                        }
                    }
                } catch (err) {
                    logger.error(`Error parsing stream chunk: ${err}`);
                }
            }
        }
    });

    deepseekStream.on("error", (err: Error) => {
        logger.error(`Stream error: ${err}`);
        transStream.end();
    });

    deepseekStream.on("end", () => {
        if (!transStream.writableEnded) {
            transStream.end();
        }
    });

    return transStream;
}

/**
 * Create completion using Claude format
 */
export async function createClaudeCompletion(
    model: string,
    messages: any[],
    system: string | undefined,
    token: string,
    stream: boolean,
    convId?: string
) {
    // Convert Claude messages to DeepSeek format
    const deepseekMessages = convertClaudeToDeepSeek(messages, system);

    // Map Claude model to DeepSeek model
    let deepseekModel = "deepseek";
    if (model.includes("opus") || model.includes("sonnet")) {
        // Use default model for Claude models
        deepseekModel = "deepseek";
    }

    if (stream) {
        const deepseekStream = await chat.createCompletionStream(
            deepseekModel,
            deepseekMessages,
            token,
            convId
        );
        return convertDeepSeekStreamToClaude(deepseekStream);
    } else {
        const deepseekResponse = await chat.createCompletion(
            deepseekModel,
            deepseekMessages,
            token,
            convId
        );
        return convertDeepSeekToClaude(deepseekResponse);
    }
}