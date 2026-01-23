# Notion Skills Example

This example demonstrates how to compile agent skills from Notion documentation.

## Setup

1. Enable the Notion provider in `colin.toml`:
   ```toml
   [[providers.notion]]
   ```

2. On first run, Colin will open a browser window for Notion OAuth authentication.

## Models

### `onboarding-skill.md`
Searches your Notion workspace for pages matching "onboarding" and compiles them into a single skill document.

### `api-reference.md`
Fetches a specific Notion page by URL. Update the URL in the template to point to your actual page.

## Running

```bash
colin run
```

## How It Works

- **`colin.notion.search(query)`** - Searches your workspace and returns all matching pages
- **`colin.notion.page(url_or_id)`** - Fetches a specific page by URL or page ID

Both methods track dependencies automatically. When a Notion page is edited, Colin detects the change and recompiles affected documents.
