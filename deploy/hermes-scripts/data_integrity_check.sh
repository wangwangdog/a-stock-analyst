#!/bin/bash
cd /home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro
exec /home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/.venv/bin/python3 /home/dogzi/.hermes/scripts/data_integrity_check.py "$@"
