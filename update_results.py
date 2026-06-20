name: Update Match Results

on:
  schedule:
    - cron: '*/30 * * * *'   # Every 30 minutes
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install requests

      - name: Fetch results and update HTML
        run: python update_results.py

      - name: Commit and push if changed
        run: |
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git config user.name "github-actions[bot]"
          git diff --quiet && echo "Nothing to commit" || (
            git add index.html &&
            git commit -m "Auto-update results $(date -u '+%d %b %Y %H:%M UTC')" &&
            git push
          )
