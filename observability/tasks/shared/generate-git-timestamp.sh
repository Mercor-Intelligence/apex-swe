#!/bin/bash

# Script to generate git commit timestamp for filtering
# This should be run in the client container where the git repo is available

echo "🔍 Generating git commit timestamp for data filtering..."

# Try to find the git repository - check /app/repo and /workspace/repo first (most common)
REPO_PATHS=("/app/repo" "/workspace/repo" "/testbed" "/workspace" "/app" "/repo" ".")
REPO_PATH=""

for path in "${REPO_PATHS[@]}"; do
    if [ -d "$path/.git" ]; then
        REPO_PATH="$path"
        echo "📍 Found git repository at: $REPO_PATH"
        break
    fi
done

if [ -z "$REPO_PATH" ]; then
    echo "❌ No git repository found in common locations"
    echo "   Searched: ${REPO_PATHS[*]}"
    exit 1
fi

# Get the current commit timestamp
TIMESTAMP=$(git -C "$REPO_PATH" log -1 --format=%cI 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$TIMESTAMP" ]; then
    echo "❌ Failed to get git commit timestamp"
    exit 1
fi

# Write timestamp to shared data directory
OUTPUT_FILE="/data/git_commit_timestamp.txt"
echo "$TIMESTAMP" > "$OUTPUT_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Git commit timestamp written to $OUTPUT_FILE"
    echo "🕐 Timestamp: $TIMESTAMP"
    echo "ℹ️  This timestamp will be used to filter issues and messages"
else
    echo "❌ Failed to write timestamp to $OUTPUT_FILE"
    exit 1
fi
