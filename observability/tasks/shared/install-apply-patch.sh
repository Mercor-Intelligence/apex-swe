#!/bin/bash
# Install apply_patch tool for GPT-5.1-codex compatibility
# This script should be called during container startup

set -e

APPLY_PATCH_SCRIPT='#!/usr/bin/env python3
"""apply_patch - GPT-5.1-codex native patch tool."""
import sys, os, re

def parse_patch(text):
    ops = []
    pattern = r"\*\*\*\s*Begin Patch(.*?)\*\*\*\s*End Patch"
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    if not matches:
        matches = [text]
    for content in matches:
        file_pattern = r"\*\*\*\s*(Add|Update|Delete)\s+File:\s*(\S+)"
        parts = re.split(file_pattern, content, flags=re.IGNORECASE)
        i = 1
        while i < len(parts) - 1:
            if i + 2 <= len(parts):
                ops.append({"op": parts[i].lower(), "path": parts[i+1].strip(), "content": parts[i+2].strip() if i+2 < len(parts) else ""})
            i += 3
    return ops

def apply_update(path, content):
    if not os.path.exists(path):
        print(f"File not found: {path}", file=sys.stderr)
        return False
    with open(path) as f:
        lines = f.read().split("\n")
    
    # Parse hunks
    patch_lines = content.split("\n")
    result = lines[:]
    dels, adds, ctx = [], [], []
    in_hunk = False
    
    for line in patch_lines:
        if line.startswith("@@"):
            if dels or adds:
                result = apply_hunk(result, ctx, dels, adds)
            in_hunk, ctx, dels, adds = True, [], [], []
            continue
        if in_hunk:
            if line.startswith("-"):
                dels.append(line[1:])
            elif line.startswith("+"):
                adds.append(line[1:])
            elif line.startswith(" "):
                if not dels and not adds:
                    ctx.append(line[1:])
                else:
                    result = apply_hunk(result, ctx, dels, adds)
                    ctx, dels, adds = [line[1:]], [], []
    
    if dels or adds:
        result = apply_hunk(result, ctx, dels, adds)
    
    with open(path, "w") as f:
        f.write("\n".join(result))
    print(f"Updated: {path}")
    return True

def apply_hunk(lines, ctx, dels, adds):
    search = ctx + dels if ctx else dels
    if not search:
        return lines + adds
    for i in range(len(lines)):
        match = True
        for j, s in enumerate(search):
            if i+j >= len(lines) or lines[i+j].strip() != s.strip():
                match = False
                break
        if match:
            return lines[:i] + list(ctx) + list(adds) + lines[i+len(search):]
    # Fallback: try matching just first deletion
    for i, line in enumerate(lines):
        if dels and line.strip() == dels[0].strip():
            cnt = sum(1 for j, d in enumerate(dels) if i+j < len(lines) and lines[i+j].strip() == d.strip())
            return lines[:i] + list(adds) + lines[i+cnt:]
    print("Warning: Could not apply hunk exactly", file=sys.stderr)
    return lines + adds

def main():
    text = sys.stdin.read()
    if not text.strip():
        print("Error: No patch content", file=sys.stderr)
        sys.exit(1)
    ops = parse_patch(text)
    if not ops:
        print("Error: No patch operations found", file=sys.stderr)
        sys.exit(1)
    ok = True
    for op in ops:
        op_type = op["op"]
        op_path = op["path"]
        op_content = op.get("content", "")
        print(f"Applying: {op_type.upper()} {op_path}")
        if op_type == "delete":
            if os.path.exists(op_path):
                os.remove(op_path)
                print(f"Deleted: {op_path}")
        elif op_type == "add":
            lines = [l[1:] if l.startswith("+") else l for l in op_content.split("\n") if not l.startswith("-") and not l.startswith("@@")]
            parent = os.path.dirname(op_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(op_path, "w") as f:
                f.write("\n".join(lines))
            print(f"Created: {op_path}")
        elif op_type == "update":
            if not apply_update(op_path, op_content):
                ok = False
    print("Patch applied!" if ok else "Some operations failed")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
'

# Install to /usr/local/bin
echo "$APPLY_PATCH_SCRIPT" > /usr/local/bin/apply_patch
chmod +x /usr/local/bin/apply_patch

echo "✓ apply_patch tool installed to /usr/local/bin/apply_patch"

