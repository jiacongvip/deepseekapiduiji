import { PassThrough } from "stream";
import _ from "lodash";
import chat from "@/api/controllers/chat.ts";
import util from "@/lib/util.ts";
import logger from "@/lib/logger.ts";

const MODEL_NAME = "qwen";

/**
 * Convert Gemini contents format to Qwen format
 * 
 * @param contents Gemini contents array
 * @param systemInstruction Optional system instruction
 */
export function convertGeminiToQwen(contents: any[], systemInstruction?: any): any[] {
    const qwenMessages: any[] = [];

    // Handle system instruction
    let systemText = "";
    if (systemInstruction) {
        if (typeof systemInstruction === "string") {
            systemText = systemInstruction;
        } else if (systemInstruction.parts) {
            systemText = systemInstruction.parts
                .filter((part: any) => part.text)
                .map((part: any) => part.text as string)
                .join("\n");
        }
    }

    let systemPrepended = false;

    for (const content of contents) {
        const role = content.role === "model" ? "assistant" : "user";

        // Extract text from parts
        let text = "";
        if (content.parts && Array.isArray(content.parts)) {
            text = content.parts
                .filter((part: any) => part.text)
                .map((part: any) => part.text as string)
                .join("\n");
        }

        // Prepend system instruction to first user message
        if (role === "user" && systemText && !systemPrepended) {
            text = `${systemText}\n\n${text}`;
            systemPrepended = true;
        }

        qwenMessages.push({
            role: role,
            content: text
        });
    }

    return qwenMessages;
}

/**
 * Convert Qwen response to Gemini format
 * 
 * @param qwenResponse Qwen response object
 */
export function convertQwenToGemini(qwenResponse: any): any {
    const content = qwenResponse.choices[0].message.content;

    return {
        candidates: [
            {
                content: {
                    parts: [
                        {
                            text: content
                        }
                    ],
                    role: "model"
                },
                finishReason: qwenResponse.choices[0].finish_reason === "stop" ? "STOP" : "MAX_TOKENS",
                index: 0,
                safetyRatings: []
            }
        ],
        usageMetadata: {
            promptTokenCount: qwenResponse.usage?.prompt_tokens || 0,
            candidatesTokenCount: qwenResponse.usage?.completion_tokens || 0,
            totalTokenCount: qwenResponse.usage?.total_tokens || 0
        }
    };
}

/**
 * Convert Qwen stream to Gemini SSE format
 * 
 * @param qwenStream Qwen stream
 */
export function convertQwenStreamToGemini(qwenStream: any): PassThrough {
    const transStream = new PassThrough();
    let contentBuffer = "";

    qwenStream.on("data", (chunk: Buffer) => {
        const lines = chunk.toString().split("\n");

        for (const line of lines) {
            if (!line.trim() || line.trim() === "data: [DONE]") continue;

            if (line.startsWith("data: ")) {
                try {
                    const data = JSON.parse(line.slice(6));

                    if (data.choices && data.choices[0]) {
                        const delta = data.choices[0].delta;

                        // Handle content delta
                        if (delta.content) {
                            contentBuffer += delta.content;
                            const geminiChunk = {
                                candidates: [
                                    {
                                        content: {
                                            parts: [
                                                {
                                                    text: delta.content
                                                }
                                            ],
                                            role: "model"
                                        },
                                        finishReason: null,
                                        index: 0,
                                        safetyRatings: []
                                    }
                                ]
                            };
                            transStream.write(`data: ${JSON.stringify(geminiChunk)}\n\n`);
                        }

                        // Handle finish
                        if (data.choices[0].finish_reason) {
                            const finalChunk = {
                                candidates: [
                                    {
                                        content: {
                                            parts: [
                                                {
                                                    text: ""
                                                }
                                            ],
                                            role: "model"
                                        },
                                        finishReason: "STOP",
                                        index: 0,
                                        safetyRatings: []
                                    }
                                ],
                                usageMetadata: {
                                    promptTokenCount: 1,
                                    candidatesTokenCount: 1,
                                    totalTokenCount: 2
                                }
                            };
                            transStream.write(`data: ${JSON.stringify(finalChunk)}\n\n`);
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
 * Create Gemini completion using Qwen backend
 * 
 * @param model Model name
 * @param contents Gemini contents
 * @param systemInstruction Optional system instruction
 * @param refreshToken Qwen refresh token
 * @param stream Whether to stream
 * @param conversationId Optional conversation ID
 */
export async function createGeminiCompletion(
    model: string,
    contents: any[],
    systemInstruction: any,
    refreshToken: string,
    stream: boolean = false,
    conversationId?: string
): Promise<any | PassThrough> {
    try {
        // Convert Gemini contents to Qwen format
        const qwenMessages = convertGeminiToQwen(contents, systemInstruction);

        if (stream) {
            // Create Qwen stream
            const qwenStream = await chat.createCompletionStream(model, qwenMessages, '', refreshToken, conversationId, 0);
            // Convert to Gemini SSE format
            return convertQwenStreamToGemini(qwenStream);
        } else {
            // Create Qwen completion
            const qwenResponse = await chat.createCompletion(model, qwenMessages, '', refreshToken, conversationId, 0);
            // Convert to Gemini format
            return convertQwenToGemini(qwenResponse);
        }
    } catch (err) {
        logger.error(`Gemini completion error: ${err}`);
        throw err;
    }
}