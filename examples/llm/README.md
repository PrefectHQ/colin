# LLM Examples

This example demonstrates Colin's `llm_classify()` filter for categorizing content into predefined labels.

## Files

- `models/source.md` - Base document with sample product feedback
- `models/extract.md` - Demonstrates the `llm_extract()` filter with a single extraction
- `models/classify.md` - Demonstrates the `llm_classify()` filter with a single classification
- `models/classify_multi_label.md` - Demonstrates multi-label classification with `multi=True`
- `models/instructions.md` - Demonstrates using instructions (system prompts) to control LLM behavior

## Run It

```bash
cd examples/llm
colin run
```

## Output

After compiling, check the `output/` directory. The compiled `classify.md` file will contain the classification result.

Set your API key before running:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

## What to Notice

1. **Extract Filter**: The `extract.md` file shows how to extract specific information from content using natural language prompts.

2. **Classify Filter**: The `classify.md` file shows how to classify content into predefined labels (positive/negative/neutral sentiment).

3. **Multi-Label Classification**: The `classify_multi_label.md` file demonstrates returning multiple applicable labels.

4. **Single LLM Calls**: Each example makes exactly one LLM call.

5. **Structured Output**: The classify filter uses structured output to ensure the result is one of the provided labels.

6. **Instructions**: The `instructions.md` file shows how to pass system prompts to control LLM behavior (e.g., making it respond like a pirate).

## Example Usage

### Extract
```jinja
{{ ref('source.md') | llm_extract('the main complaints or negative feedback mentioned') }}
```

### Single Label Classification
```jinja
{{ ref('source.md') | llm_classify(labels=['positive', 'negative', 'neutral']) }}
```

### Multi-Label Classification
```jinja
{{ ref('source.md') | llm_classify(labels=['interface', 'performance', 'pricing'], multi=True) }}
```

### Instructions (System Prompts)
```jinja
{{ ref('source.md') | llm_extract('summarize', instructions='Talk like a pirate.') }}
```

Or with the `{% llm %}` block:
```jinja
{% llm instructions='Talk like a pirate.' %}
Summarize this: {{ ref('source.md').content }}
{% endllm %}
```
