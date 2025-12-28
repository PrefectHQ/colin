You are extracting specific information from content.

## Content
{{ content }}

## Task
Extract: {{ prompt }}

{% if previous_output %}
## Previous Output
The following was extracted previously. If the content hasn't changed meaningfully, you may respond with UseExisting to maintain stability.

{{ previous_output }}
{% endif %}

## Response
Provide the extracted information. If previous output exists and is still valid, respond with UseExisting instead.
