#!/bin/bash
# Read-only, no amounts: which provider/model and which MCP tools served the owner's first
# Telegram questions since the 22:07 switch, and what Finance answered (status codes only).
cd /
echo "== hermes agent.log since 22:07: providers/models/tools (counts only)"
sudo -n -u home-agent awk '$1" "$2 >= "2026-11-07 22:07"' /home/home-agent/.hermes/logs/agent.log 2>/dev/null \
 | grep -o -E "(provider[=:] ?['\"]?[a-z][a-z-]+|model[=:] ?['\"]?(gpt|kimi)[A-Za-z0-9._-]*|mcp_[a-z]+_[a-z_]+|(openai-codex|kimi-coding|moonshot)|HTTP [0-9]{3}|Traceback|ERROR)" \
 | tr -d "'\"" | sort | uniq -c | sort -rn | head -25
echo "== gateway errors.log since 22:07 (first words only)"
sudo -n -u home-agent awk '$1" "$2 >= "2026-11-07 22:07"' /home/home-agent/.hermes/logs/errors.log 2>/dev/null | cut -c1-110 | sed -E 's/[0-9]+[.,][0-9]{2}/<n>/g' | tail -8
echo "== finance-api requests since 22:07 (method path status, ids masked)"
sudo -n -u svc-finance bash -c 'export XDG_RUNTIME_DIR=/run/user/$(id -u); journalctl --user -u finance-api --since "2026-11-07 22:07" -o cat --no-pager' 2>/dev/null \
 | grep -o -E '"(GET|POST) [^ ]+ HTTP/[0-9.]+" [0-9]{3}' | sed -E 's/\?[^ ]*//; s/[0-9a-f-]{20,}/<id>/g' | sort | uniq -c
