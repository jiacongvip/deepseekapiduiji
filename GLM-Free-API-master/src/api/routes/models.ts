import _ from 'lodash';

// 支持的模型列表，基于官方API返回的模型
const SUPPORTED_MODELS = [
    {
        "id": "glm-4.6",
        "name": "GLM-4.6",
        "object": "model",
        "owned_by": "glm-free-api",
        "description": "高智能旗舰 - 智谱最强性能，高级编码能力、强大推理以及工具调用能力"
    },
    {
        "id": "glm-4.5",
        "name": "GLM-4.5",
        "object": "model",
        "owned_by": "glm-free-api",
        "description": "超强性能 - 性能优秀，强大的推理能力、代码生成能力以及工具调用能力"
    },
    {
        "id": "glm-4.5-x",
        "name": "GLM-4.5-X",
        "object": "model",
        "owned_by": "glm-free-api",
        "description": "超强性能-极速版 - 推理速度更快，适用于搜索问答、智能助手、实时翻译等时效性较强场景"
    },
    {
        "id": "glm-4.5-air",
        "name": "GLM-4.5-Air",
        "object": "model",
        "owned_by": "glm-free-api",
        "description": "高性价比 - 在推理、编码和智能体任务上表现强劲"
    }
];

export default {

    prefix: '/v1',

    get: {
        '/models': async () => {
            return {
                "data": SUPPORTED_MODELS
            };
        }

    }
}

// 导出模型验证函数
export function isValidModel(modelId: string): boolean {
    return SUPPORTED_MODELS.some(model => model.id === modelId);
}

// 导出默认模型
export const DEFAULT_MODEL = "glm-4.6";