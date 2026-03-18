#!/bin/bash

# Ensure uv is available
export PATH="$HOME/.local/bin:$PATH"

uv run pytest $TEST_DIR/test_outputs.py -rA

