# 更新日志 (Changelog)

## [v0.2.2] - 2026-01-13 下午

### 🐛 重要修复

#### 🔍 修复搜索引用解析逻辑
- **修复**: 根据真实数据结构重写引用解析代码
- **真实结构**: 搜索结果在 `patch_op.patch_value.content_block[block_type=10025].search_query_result_block`
- **新增字段**: `sitename`（网站名称）, `publish_time`（发布时间）
- **优化**: 同时支持 `patch_op` 和 `message.content_block` 两种解析路径
- **去重**: 基于URL进行引用去重，避免重复条目

### 📝 数据结构变更

**之前（错误假设）**:
```json
{
  "message": {
    "references": [...]  // 实际不存在这个字段
  }
}
```

**现在（真实结构）**:
```json
{
  "patch_op": [{
    "patch_value": {
      "content_block": [{
        "block_type": 10025,
        "content": {
          "search_query_result_block": {
            "summary": "搜索 2 个关键词，参考 10 篇资料",
            "queries": ["关键词1", "关键词2"],
            "results": [{
              "text_card": {
                "title": "网站标题",
                "url": "https://...",
                "summary": "摘要",
                "sitename": "网站名",
                "publish_time_second": "2025-10-29T07:50:20+08:00",
                "index": 1
              }
            }]
          }
        }
      }]
    }
  }]
}
```

### 📄 文档更新

- 新增: `数据结构说明.md` - 详细的真实数据结构文档
- 更新: `引用网站功能说明.md` - 反映真实解析逻辑
- 更新: `test_references.py` - 测试脚本兼容新字段

### 🎯 新增字段

ReferenceItem 模型新增字段：
- `sitename` (可选) - 网站名称，如"常州飞傲软件科技有限公司"
- `publish_time` (可选) - 发布时间，ISO格式，如"2025-10-29T07:50:20+08:00"

### ⚠️ 破坏性变更

**无** - 向下兼容，新字段为可选

---

## [v0.2.1] - 2026-01-13 上午

### ✨ 新增功能

#### 🔍 搜索引用来源功能
- **新增**: API响应中现在包含 `references` 字段，可获取豆包搜索时引用的网站列表
- **新增**: `ReferenceItem` 数据模型，包含以下信息：
  - `title`: 网站标题
  - `url`: 网站链接
  - `snippet`: 内容摘要（可选）
  - `index`: 引用序号（可选）

### 📝 API变更

#### CompletionResponse 响应模型更新

**之前**:
```json
{
  "text": "回答内容",
  "img_urls": [],
  "conversation_id": "xxx",
  "messageg_id": "yyy",
  "section_id": "zzz"
}
```

**现在**:
```json
{
  "text": "回答内容",
  "img_urls": [],
  "references": [                    // ⭐ 新增字段
    {
      "title": "参考网站标题",
      "url": "https://example.com",
      "snippet": "内容摘要",
      "index": 1
    }
  ],
  "conversation_id": "xxx",
  "messageg_id": "yyy",
  "section_id": "zzz"
}
```

### 🔧 实现细节

- 在 `handle_sse()` 函数中新增对消息 `references` 字段的解析
- 自动去重，避免重复的引用条目
- 兼容无引用的普通回答（返回空数组）
- 不影响现有功能，向下兼容

### 📄 文档更新

- 新增: `引用网站功能说明.md` - 详细的功能使用文档
- 新增: `test_references.py` - 测试脚本，支持交互模式和自动测试
- 更新: API文档 (http://localhost:8000/docs)

### 🧪 测试

提供了完整的测试脚本 `test_references.py`，支持三种使用方式：

```bash
# 交互模式
python3 test_references.py

# 直接提问
python3 test_references.py "2026年最新的科技新闻"

# 运行自动测试
python3 test_references.py test
```

### 📚 使用场景

1. **验证信息来源** - 查看豆包的回答基于哪些网站
2. **学术引用** - 自动生成参考文献列表
3. **事实核查** - 追溯信息的原始来源
4. **延伸阅读** - 获取相关网站进行深入了解

### ⚠️ 注意事项

- 并非所有回答都有引用（常识性问题可能不触发搜索）
- 引用数量不固定，取决于豆包的搜索结果
- `snippet` 和 `index` 字段可能为空

---

## [v0.2.0] - 2026-01-13

### 初始功能

- 聊天补全接口
- 文件上传功能
- 会话管理
- SSE流式响应
- 游客模式支持
- 深度思考模式

---

*Note: 版本号遵循语义化版本 2.0.0*

