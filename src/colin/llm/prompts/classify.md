You are classifying content into one of the provided categories.

## Content
{{ content }}

## Available Labels
{% for label in labels %}
- {{ label }}
{% endfor %}

{% if multi %}
## Task
Classify the content into one or more of the labels above. Return a list of applicable labels.
{% else %}
## Task
Classify the content into exactly one of the labels above.
{% endif %}

{% if previous_output %}
## Previous Output
The following classification was made previously. If the content hasn't changed meaningfully, you may respond with UseExisting to maintain stability.

{{ previous_output }}
{% endif %}

## Response
{% if multi %}
Provide a list of labels that best classify the content. If previous output exists and is still valid, respond with UseExisting instead.
{% else %}
Provide exactly one label from the list above. If previous output exists and is still valid, respond with UseExisting instead.
{% endif %}
