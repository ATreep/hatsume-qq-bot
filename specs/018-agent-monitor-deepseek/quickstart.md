# Quickstart: Agent Monitor & Deepseek Provider

## Prerequisites

- Python 3.12+
- Running hatsume bot instance
- Deepseek API key (obtain from https://platform.deepseek.com/)

## Configuration

1. Edit `.env.prod` and set your Deepseek API key:
   ```
   DEEPSEEK_API_KEY=sk-your-key-here
   ```

2. Restart the bot (`nb run`)

## Using Agent Monitor

The chat agent (初芽) can now:

### Check agent status
Ask 初芽: "coding_agent 现在在做什么？"
→ The LLM will call `check_agent("coding_agent")` and report status.

### Allocate agent (with guard)
Ask 初芽 to perform a coding task.
→ If coding_agent is already running, allocation is rejected with a "busy" message.
→ If idle/done, allocation proceeds normally.

## Testing

```bash
# Test Deepseek provider
python -m pytest tests/test_deepseek_provider.py -v

# Test agent monitor
python -m pytest tests/test_agent_monitor.py -v

# Full regression
python -m pytest tests/ -v
```
