# LLM Examples

This example demonstrates Colin's `llm_classify()` filter for categorizing content into predefined labels.

## Files

- `models/source.md` - Base document with sample product feedback
- `models/extract.md` - Demonstrates the `llm_extract()` filter with a single extraction
- `models/classify.md` - Demonstrates the `llm_classify()` filter with a single classification
- `models/classify_multi_label.md` - Demonstrates multi-label classification with `multi=True`

## Run It

```bash
cd examples/llm
colin run
```

## Output

After compiling, check the `target/` directory. The compiled `classify.md` file will contain the classification result.

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

## Example Usage

### Extract
```jinja
{{ ref('source') | llm_extract('the main complaints or negative feedback mentioned') }}
```

### Single Label Classification
```jinja
{{ ref('source') | llm_classify(labels=['positive', 'negative', 'neutral']) }}
```

### Multi-Label Classification
```jinja
{{ ref('source') | llm_classify(labels=['interface', 'performance', 'pricing'], multi=True) }}
```
