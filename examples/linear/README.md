# Linear Example

This example demonstrates using the Linear provider to create a sprint status skill.

## Setup

1. Run `colin run` from this directory
2. On first run, a browser opens for Linear OAuth authorization
3. After authorization, the skill compiles with your Linear issues

## What it does

The `sprint-status.md` model fetches issues from your Linear workspace and generates a status report showing in-progress and todo issues.

## Customization

Edit `models/sprint-status.md` to:
- Filter by team: `colin.linear.issues(team="Engineering")`
- Filter by assignee: `colin.linear.issues(assignee="me")`
- Change states: `colin.linear.issues(state="Done")`
- Adjust limits: `colin.linear.issues(limit=50)`
