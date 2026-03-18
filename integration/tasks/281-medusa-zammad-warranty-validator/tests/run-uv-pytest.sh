#!/bin/bash

# Ensure uv is available
source $HOME/.local/bin/env

uv run pytest $TEST_DIR/test_outputs.py -rA

