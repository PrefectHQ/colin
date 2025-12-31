---
name: Data Analysis
description: Extracted insights from product data
---
# Product Analysis

{{ mcp.demo.resource('demo://greeting/Analyst') }}

## Key Pain Points
{{ ref('data') | llm_extract('List the top 3 user pain points mentioned in the feedback, as bullet points') }}

## Performance Summary
{{ ref('data') | llm_extract('Summarize the technical performance in one sentence') }}

## Strengths
{{ ref('data') | llm_extract('What are users happy about? List as bullet points') }}

## Analysis Guidance
{{ mcp.demo.prompt('summarize', style='detailed') }}
