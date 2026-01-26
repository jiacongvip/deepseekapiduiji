import { PassThrough } from "stream";
import _ from "lodash";
import chat from "@/api/controllers/chat.ts";
import util from "@/lib/util.ts";
import logger from "@/lib/logger.ts";

const MODEL_NAME = "qwen";

/**
 * Convert Claude messages format to Qwen format
 * 
 * @param messages Claude messages array
 * @param system Optional system message (string or array format)
 */
export function convertClaudeToQwen(messages: any[], system?: string | any[]): any[] {
    const qwenMessages: any[] = [];

    // Convert system to string if it's an array
    let systemText: string | undefined = undefined;
    if (system) {
        if (Array.isArray(system)) {
            // Extract text from array format system message
            systemText = system
                .filter((item: any) => item.type === "text")
                .map((item: any) => item.text as string)
                .join("\n");
        } else if (typeof system === "string") {
            systemText = system;
        }
    }

    // If there's a system message, prepend it to the first user message
    let systemPrepended = false;

    for (const msg of messages) {
        if (msg.role === "user") {
            let content: string = msg.content || "";

            // Handle content array format
            if (Array.isArray(msg.content)) {
                content = msg.content
                    .filter((item: any) => item.type === "text")
                    .map((item: any) => item.text as string)
                    .join("\n");
            }

            // Prepend system message to first user message
            if (systemText && !systemPrepended) {
                content = `${systemText}\n\n${content}`;
                systemPrepended = true;
            }

            qwenMessages.push({
                role: "user",
                content: content
            });
        } else if (msg.role === "assistant") {
            let content: string = msg.content || "";

            // Handle content array format
            if (Array.isArray(msg.content)) {
                content = msg.content
                    .filter((item: any) => item.type === "text")
                    .map((item: any) => item.text as string)
                    .join("\n");
            }

            qwenMessages.push({
                role: "assistant",
                content: content
            });
        }
    }

    return qwenMessages;
}

/**
 * Convert Qwen response to Claude format
 * 
 * @param qwenResponse Qwen response object
 */
export function convertQwenToClaude(qwenResponse: any): any {
    const content = qwenResponse.choices[0].message.content;

    return {
        id: qwenResponse.id || util.uuid(),
        type: "message",
        role: "assistant",
        content: [
            {
                type: "text",
                text: content
            }
        ],
        model: MODEL_NAME,
        stop_reason: qwenResponse.choices[0].finish_reason === "stop" ? "end_turn" : "max_tokens",
        stop_sequence: null,
        usage: {
            input_tokens: qwenResponse.usage?.prompt_tokens || 0,
            output_tokens: qwenResponse.usage?.completion_tokens || 0
        }
    };
}

/**
 * Convert Qwen stream to Claude SSE format
 * 
 * @param qwenStream Qwen stream
 */
export function convertQwenStreamToClaude(qwenStream: any): PassThrough {
    const transStream = new PassThrough();
    const messageId = util.uuid();
    let contentBuffer = "";
    let isFirstChunk = true;

    qwenStream.on("data", (chunk: Buffer) => {
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

    qwenStream.on("error", (err: any) => {
        logger.error(`Qwen stream error: ${err}`);
        transStream.end();
    });

    qwenStream.on("close", () => {
        if (!transStream.closed) {
            transStream.end();
        }
    });

    return transStream;
}

/**
 * Create Claude completion using Qwen backend
 * 
 * @param model Model name
 * @param messages Claude messages
 * @param system Optional system message
 * @param refreshToken Qwen refresh token
 * @param stream Whether to stream
 * @param conversationId Optional conversation ID
 */
export async function createClaudeCompletion(
    model: string,
    messages: any[],
    system: string | any[] | undefined,
    refreshToken: string,
    stream: boolean = false,
    conversationId?: string
): Promise<any | PassThrough> {
    try {
        // Convert Claude format to Qwen format
        const qwenMessages = convertClaudeToQwen(messages, system);

        if (stream) {
            // Create Qwen stream
            const qwenStream = await chat.createCompletionStream(model, qwenMessages, '', refreshToken, conversationId, 0);
            // Convert to Claude SSE format
            return convertQwenStreamToClaude(qwenStream);
        } else {
            // Create Qwen completion
            const qwenResponse = await chat.createCompletion(model, qwenMessages, '', refreshToken, conversationId, 0);
            // Convert to Claude format
            return convertQwenToClaude(qwenResponse);
        }
    } catch (err) {
        logger.error(`Claude completion error: ${err}`);
        throw err;
    }
}