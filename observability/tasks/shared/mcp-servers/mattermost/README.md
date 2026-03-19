# mcp-server-mattermost

This project implements a Model Context Protocol (MCP) server for Mattermost integration. It connects to Mattermost API endpoints to retrieve and process various information, making it available through standard MCP transports.

## Features

- Secure, token-based connection to Mattermost API endpoints
- Supports multiple transport modes:
  - `stdio`
  - `http-stream`
  - `sse`
- Search for messages across multiple Mattermost channels
- Customizable default channels and message fetch limits

## Requirements

- Node.js >= 22
- npm >= 10

## Setup

1. Clone this repository:

```bash
git clone https://github.com/kakehashi-inc/mcp-server-mattermost.git
cd mcp-server-mattermost
```

2. Install dependencies:

```bash
npm install
```

3. Set up your environment variables:

### Required Environment Variables

- `MATTERMOST_ENDPOINT`: Your Mattermost server URL
- `MATTERMOST_TOKEN`: Your Mattermost authentication token
- `MATTERMOST_TEAM`: The name of the team to monitor
- `MATTERMOST_CHANNELS`: Comma-separated list of channel names to monitor

### Environment Variable Setup Options

#### Option 1: Direct Environment Variables
```bash
export MATTERMOST_ENDPOINT="https://your-mattermost-server.com"
export MATTERMOST_TOKEN="your-token-here"
export MATTERMOST_TEAM="your-team-name"
export MATTERMOST_CHANNELS="general,random,dev"
```

#### Option 2: Using .env file (with dotenvx)
```bash
# Install dotenvx (optional)
npm install -g @dotenvx/dotenvx

# Create .env file
cp .env.example .env
# Edit .env file with your values

# Encrypt your .env file (recommended for production)
dotenvx encrypt
```

4. Build the server:

```bash
npm run build
```

## Usage

The server supports three transport modes: stdio (default), sse, and http-stream.

### Standard I/O Transport Mode

```bash
# Using npm scripts (with dotenvx)
npm run start:stdio

# Direct execution
node dist/main.js --transport stdio

# Using npx
npx mcp-server-mattermost --transport stdio
```

### SSE Transport Mode

```bash
# Using npm scripts (with dotenvx)
npm run start:sse

# Direct execution
node dist/main.js --transport sse
```

### HTTP Transport Mode

```bash
# Using npm scripts (with dotenvx)
npm run start:http

# Direct execution
node dist/main.js --transport http-stream
```

## Claude Desktop Integration

To use this MCP server with Claude Desktop, add the following configuration to your Claude Desktop settings:

### Sample Configuration

```json
{
  "mcpServers": {
    "mattermost": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-server-mattermost@latest",
        "--transport", "stdio",
        "--endpoint", "https://your-mattermost-server/api/v4",
        "--token", "your_personal_access_token",
        "--team", "your_team_name",
        "--channels", "town-square,general,your_channel_name"
      ]
    }
  }
}
```

## Development

- `npm run dev`: Start the server in development mode with hot reload
- `npm run lint`: Run ESLint
- `npm run format`: Format code using Prettier
- `npm test`: Run tests
- `npm run inspect`: Run MCP inspector

## References

- [Model Context Protocol TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP inspector](https://github.com/modelcontextprotocol/inspector)

## License

MIT
