# 模型与供应商配置

供应商连接与模型角色分别保存在项目根目录下的两份 YAML 文件中：

- `data/hatsume-plugin/providers.yml`：完整 SDK Base URL、API Key、支持的 API。
- `data/hatsume-plugin/models.yml`：各角色使用的供应商、API、模型 ID 与选项。

模型工厂每次创建客户端都重新读取并校验这两份文件。命令修改立即落盘，下一次调用生效；已经创建的客户端继续使用该次调用的配置快照。重启后保留所有选择。当前配置为全局配置，适用于所有群。

## 首次配置

已有部署的配置已从旧源码和环境迁移到这两份文件，保留高级、轻量、迷你、代码、视觉、System One、Embedding 和 SenseNova 图片模型选择。运行时代码不再从环境读取模型 API Key。

新部署可以复制 `examples/model-config/providers.yml` 和 `examples/model-config/models.yml`，然后填写自己的 Key 并选择实际可用的模型。这些示例只是格式示范，不代表迁移现有记忆向量的方案；若更换 Embedding 模型，必须同时重建已有记忆向量，并保持向量维度与当前存储一致。System One 保留独立的结构化协议：当前聊天判断使用 `/systemone`，共享桌面协调请求使用 `/decisions`，供应商必须支持对应路由。

两份文件都不存在时，Store 会创建空配置，允许管理员通过命令设置。如果仅一份文件丢失，程序会报错并要求恢复，不会覆盖剩余文件。YAML 格式错误和不兼容的配置会被拒绝。

文件通过同目录临时文件和原子替换保存，权限为 `0600`。`data/` 被主仓库忽略；如果运行数据有独立 Git 仓库，也必须在其 `.gitignore` 中忽略 `providers.yml` 与 `models.yml`。Provider 查询只显示 Key 是否配置，不显示 Key 值。

## 配置格式

```yaml
# providers.yml
schema_version: 1
providers:
  my-provider:
    base_url: https://example.com/v1
    api_key: ''
    supported_apis:
      - openai_chat_completions
      - openai_responses
```

```yaml
# models.yml
schema_version: 1
roles:
  advance:
    provider: my-provider
    api: openai_responses
    model: your-model-id
    options: {}
```

`base_url` 必须是完整 SDK 地址。OpenAI 兼容接口的 `/v1`、Ark 的 `/v3` 或自定义路径写在配置中，工厂不会追加 API 版本后缀。Google 使用其原生 API Base URL，不使用 OpenAI 兼容路径。URL 不允许嵌入用户名、密码、查询参数或 fragment。

Provider ID 使用字母、数字、`_`、`-`。模型 ID 直接使用供应商接受的名称，不需要修改源码或加入固定模型名称列表。

## 管理员命令

`/model` 和 `/provider` 都检查 `ADMIN_QQ_ID`。命令被处理后不会进入群聊历史或模型上下文。命令支持引号包裹参数。

```text
/model
/model list
/model help
/model use advance my-provider your-model-id --api openai_responses
/model use lite my-provider another-model --api openai_chat_completions
/model use coding google your-google-model --api google_genai
/model another-model
/model options advance reasoning_effort high
/model options advance reasoning_effort null
/model options coding thinking_level low
/model check advance
```

`/model <model>` 保留原有快捷用法，使用当前高级模型的供应商与 API。`use` 在供应商仅支持一种适用于该角色的 API 时可以省略 `--api`；同一供应商下切换模型时也可以沿用该角色已选定的 API。否则需要明确指定。

切换模型、供应商或 API 会清除旧模型的选项，避免把不支持的 reasoning、token 限制或 Google thinking 配置传给新模型。重复选择完全相同的配置会保留选项。`options ... null` 删除对应选项。

`check` 只适用于聊天角色，会发送一条短请求，可能产生供应商费用；最长等待 30 秒。结果不回显模型回复或原始 SDK 错误。

```text
/provider list
/provider show my-provider
/provider help
/provider add my-provider --base-url https://example.com/v1 --api openai_chat_completions,openai_responses
/provider update my-provider --base-url https://example.com/custom/v3
/provider remove my-provider
```

删除供应商前必须先把引用它的角色切换到其他供应商。更新支持的 API 时也会检查是否与当前角色配置兼容。

API Key 只能直接写入 `providers.yml`，文件必须保持 owner-only 权限。命令不接受 Key 参数，避免凭证进入 OneBot 事件日志、聊天记录或模型上下文。

## API、角色与选项

| 角色 | API |
|---|---|
| `advance`, `lite`, `mini`, `coding`, `vision` | `openai_chat_completions`, `openai_responses`, `google_genai` |
| `systemone` | `systemone` |
| `embedding` | `openai_embeddings` |
| `image_sensenova` | `sensenova_images` |

这次只新增三种标准聊天 API 的可切换适配器。SenseNova 图片和 System One 适配器保留，其供应商与模型选择也改为读取 YAML。需要特殊 `extra_body` 的聊天供应商可以保存为 `supported_apis: []`，本轮不能选为聊天模型。

| API | 可配置选项 |
|---|---|
| OpenAI Chat Completions / Responses | `reasoning_effort`, `temperature`, `max_tokens` |
| Google GenAI | `thinking_budget` 或 `thinking_level`, `temperature`, `max_tokens` |
| OpenAI Embeddings | `chunk_size`, `dimensions` |

选项只有显式配置才会发送，不给新模型自动加 reasoning 参数。Google `thinking_budget` 和 `thinking_level` 不能同时使用。选项是否被具体模型支持由供应商决定，可用 `/model check` 验证。两种 OpenAI API 明确指定 `use_responses_api`，Responses 不自动使用前一个 response ID；应用继续管理消息历史。

## 验证

聚焦测试为 `tests/test_model_config.py`、`tests/test_model_commands.py` 和 `tests/test_model_protocols.py`。协议测试使用真实 SDK 访问本地 HTTP Server，不调用收费模型 API。使用本地 Python 环境分别并行运行；不要使用或修改项目 `.venv`，也不需要运行整个测试集合。
