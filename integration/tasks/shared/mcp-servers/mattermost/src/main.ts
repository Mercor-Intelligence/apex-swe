#!/usr/bin/env node

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express, { Request, Response } from 'express';
import { randomUUID } from 'crypto';
import { config } from './config/config.js';
import { mattermostChannels } from './mcp-tools/mattermost_channels.js';
import { mattermostFetch } from './mcp-tools/mattermost_fetch.js';
import { mattermostSearch } from './mcp-tools/mattermost_search.js';
import { consoleWriter } from './utils/console-writer.js';

const mcp = new McpServer({
  name: process.env.npm_package_name ?? 'mcp-server-mattermost',
  version: process.env.npm_package_version ?? '0.0.1',
});

// MCPツールの登録
mcp.tool(
  mattermostChannels.name,
  mattermostChannels.description,
  mattermostChannels.parameters,
  mattermostChannels.execute
);
mcp.tool(
  mattermostFetch.name,
  mattermostFetch.description,
  mattermostFetch.parameters,
  mattermostFetch.execute
);
mcp.tool(
  mattermostSearch.name,
  mattermostSearch.description,
  mattermostSearch.parameters,
  mattermostSearch.execute
);

// クリーンアップ処理を行う関数
async function cleanup(): Promise<void> {
  consoleWriter.log('Shutting down...');
  try {
    // MCPサーバーのクリーンアップ
    await mcp.close();
  } catch (error: unknown) {
    consoleWriter.error('Error during cleanup:', error);
  }
  process.exit(0);
}

// シグナルハンドラーの登録
const handleSignal = () => {
  void cleanup();
};

process.on('SIGINT', handleSignal);
process.on('SIGTERM', handleSignal);

// 予期せぬエラーのハンドリング
process.on('uncaughtException', error => {
  console.error('Uncaught exception:', error);
  void cleanup();
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled rejection at:', promise, 'reason:', reason);
  void cleanup();
});

// タイプに合わせて処理を実行
if (config.transport === 'http-stream') {
  // Streamable httpモードの場合
  const app = express();
  app.use(express.json());

  // セッション管理用のトランスポートマップ
  const transports = new Map<string, StreamableHTTPServerTransport>();

  // POST /mcpエンドポイント - クライアントからサーバーへの通信
  app.post('/mcp', async (req: Request, res: Response) => {
    try {
      // セッションIDをヘッダーから取得
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      let transport: StreamableHTTPServerTransport;

      if (sessionId && transports.has(sessionId)) {
        // 既存のセッションを使用
        const existingTransport = transports.get(sessionId);
        if (!existingTransport) {
          throw new Error('Transport not found for session ID');
        }
        transport = existingTransport;
      } else {
        // 新しいセッションを作成
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: newSessionId => {
            transports.set(newSessionId, transport);
          },
        });

        // トランスポートが閉じられた時のクリーンアップ
        transport.onclose = () => {
          if (transport.sessionId) {
            transports.delete(transport.sessionId);
          }
        };

        // MCPサーバーに接続
        await mcp.connect(transport);
      }

      // リクエストを処理
      await transport.handleRequest(req, res, req.body);
    } catch (error: unknown) {
      consoleWriter.error('Error handling MCP request:', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: 'Internal server error',
          },
          id: null,
        });
      }
    }
  });

  // GET /mcpエンドポイント - サーバーからクライアントへの通知（SSE）
  app.get('/mcp', async (req: Request, res: Response) => {
    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      if (!sessionId || !transports.has(sessionId)) {
        res.status(400).send('Invalid or missing session ID');
        return;
      }

      const transport = transports.get(sessionId);
      if (!transport) {
        res.status(400).send('Transport not found for session ID');
        return;
      }
      await transport.handleRequest(req, res);
    } catch (error: unknown) {
      consoleWriter.error('Error handling GET request:', error);
      if (!res.headersSent) {
        res.status(500).send('Internal server error');
      }
    }
  });

  // DELETE /mcpエンドポイント - セッション終了
  app.delete('/mcp', async (req: Request, res: Response) => {
    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      if (!sessionId || !transports.has(sessionId)) {
        res.status(400).send('Invalid or missing session ID');
        return;
      }

      const transport = transports.get(sessionId);
      if (!transport) {
        res.status(400).send('Transport not found for session ID');
        return;
      }
      await transport.handleRequest(req, res);
    } catch (error: unknown) {
      consoleWriter.error('Error handling DELETE request:', error);
      if (!res.headersSent) {
        res.status(500).send('Internal server error');
      }
    }
  });

  consoleWriter.log(`MCP Streamable HTTP Server is running on port ${config.port.toString()}`);

  app.listen(config.port);
} else if (config.transport === 'sse') {
  // SSEモードの場合
  const app = express();

  // to support multiple simultaneous connections we have a lookup object from
  // sessionId to transport
  const transports = new Map<string, SSEServerTransport>();

  app.get('/sse', async (_: Request, res: Response) => {
    const transport = new SSEServerTransport('/messages', res);
    transports.set(transport.sessionId, transport);
    res.on('close', () => {
      transports.delete(transport.sessionId);
    });
    await mcp.connect(transport);
  });

  app.post('/messages', async (req: Request, res: Response) => {
    const sessionId = req.query.sessionId as string;
    const transport = transports.get(sessionId);
    if (transport) {
      await transport.handlePostMessage(req, res);
    } else {
      res.status(400).send('No transport found for sessionId');
    }
  });

  consoleWriter.log(`MCP SSE Server is running on port ${config.port.toString()}`);

  app.listen(config.port);
} else {
  // stdioモードの場合
  const transport = new StdioServerTransport();

  await mcp.connect(transport);
}
