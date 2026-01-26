import { PassThrough } from "stream";
import _ from "lodash";
import chat from "@/api/controllers/chat.ts";
import util from "@/lib/util.ts";
import logger from "@/lib/logger.ts";

const MODEL_NAME = "deepseek-chat";

/**
 * Convert Gemini contents format to DeepSeek format
 * 
 * @param contents Gemini contents array
 * @param systemInstruction Optional system instruction
 */
export function convertGeminiToDeepSeek(contents: any[], systemInstruction?: any): any[] {
    const deepseekMessages: any[] = [];

    // Handle system instruction
    let systemText = "";
    if (systemInstruction) {
        if (typeof systemInstruction === "string") {
            systemText = systemInstruction;
        } else if (systemInstruction.parts) {
            systemText = systemInstruction.parts
                .filter((part: any) => part.text)
                .map((part: any) => part.text)
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
                .map((part: any) => part.text)
                .join("\n");
        }

        // Prepend system instruction to first user message
        if (role === "user" && systemText && !systemPrepended) {
            text = `${systemText}\n\n${text}`;
            systemPrepended = true;
        }

        deepseekMessages.push({
            role: role,
            content: text
        });
    }

    return deepseekMessages;
}

/**
 * Convert DeepSeek response to Gemini format
 * 
 * @param deepseekResponse DeepSeek response object
 */
export function convertDeepSeekToGemini(deepseekResponse: any): any {
    const content = deepseekResponse.choices[0].message.content;
    const reasoningContent = deepseekResponse.choices[0].message.reasoning_content || "";

    // Combine reasoning and content if reasoning exists
    const fullContent = reasoningContent
        ? `${reasoningContent}\n\n${content}`
        : content;

    return {
        candidates: [
            {
                content: {
                    parts: [
                        {
                            text: fullContent
                        }
                    ],
                    role: "model"
                },
                finishReason: deepseekResponse.choices[0].finish_reason === "stop" ? "STOP" : "MAX_TOKENS",
                index: 0,
                safetyRatings: []
            }
        ],
        usageMetadata: {
            promptTokenCount: deepseekResponse.usage?.prompt_tokens || 0,
            candidatesTokenCount: deepseekResponse.usage?.completion_tokens || 0,
            totalTokenCount: deepseekResponse.usage?.total_tokens || 0
        }
    };
}

/**
 * Convert DeepSeek stream to Gemini SSE format
 * 
 * @param deepseekStream DeepSeek stream
 */
export function convertDeepSeekStreamToGemini(deepseekStream: any): PassThrough {
    const transStream = new PassThrough();
    let contentBuffer = "";
    let reasoningBuffer = "";

    deepseekStream.on("data", (chunk: Buffer) => {
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

                        // Handle reasoning content delta
                        if (delta.reasoning_content) {
                            reasoningBuffer += delta.reasoning_content;
                            const geminiChunk = {
                                candidates: [
                                    {
                                        content: {
                                            parts: [
                                                {
                                                    text: delta.reasoning_content
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
 * Create completion using Gemini format
 */
export async function createGeminiCompletion(
    model: string,
    contents: any[],
    systemInstruction: any,
    token: string,
    stream: boolean,
    convId?: string
) {
    // Convert Gemini contents to DeepSeek format
    const deepseekMessages = convertGeminiToDeepSeek(contents, systemInstruction);

    // Map Gemini model to DeepSeek model
    let deepseekModel = "deepseek";
    if (model.includes("pro") || model.includes("flash")) {
        // Use default model for Gemini models
        deepseekModel = "deepseek";
    }

    if (stream) {
        const deepseekStream = await chat.createCompletionStream(
            deepseekModel,
            deepseekMessages,
            token,
            convId
        );
        return convertDeepSeekStreamToGemini(deepseekStream);
    } else {
        const deepseekResponse = await chat.createCompletion(
            deepseekModel,
            deepseekMessages,
            token,
            convId
        );
        return convertDeepSeekToGemini(deepseekResponse);
    }
}