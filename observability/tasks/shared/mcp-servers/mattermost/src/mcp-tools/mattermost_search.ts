import { z, ZodTypeAny } from 'zod';
import { MattermostClient } from '../mattermost/client.js';
import { config } from '../config/config.js';
import type { Message } from '../mattermost/client.js';
import { consoleWriter } from '../utils/console-writer.js';

const name = 'mattermost_search';

const description =
  'Search messages from Mattermost channels. return json of messages grouped by channel.';

const parameters = {
  query: z.string().describe('Search query to filter messages.'),
  channels: z
    .array(z.string())
    .optional()
    .describe(
      'List of channel names to fetch messages from. If not provided, uses the default channels.'
    ),
  before: z.string().optional().describe('Search before this timestamp (yyyy-mm-dd).'),
  after: z.string().optional().describe('Search after this timestamp (yyyy-mm-dd).'),
  on: z.string().optional().describe('Search on this date (yyyy-mm-dd).'),
  limit: z
    .number()
    .min(1)
    .optional()
    .describe(
      'Maximum number of messages to fetch per channel. If not provided, uses the default limit.'
    ),
};

type Args = z.objectOutputType<typeof parameters, ZodTypeAny>;

const execute = async ({ query, channels, before, after, on, limit }: Args) => {
  const client = new MattermostClient(config.endpoint, config.token);
  const targetChannels = await client.getTargetChannelNames(channels, config.channels);
  const messageLimit = limit ?? config.limit;

  const messages: { type: 'text'; text: string }[] = [];

  // クエリ未指定はエラーを返す
  if (!query) {
    throw new Error('Query is required');
  }

  for (const channelName of targetChannels) {
    if (config.transport !== 'stdio') {
      let paramString = `query: ${query}`;
      if (before) {
        paramString += `, before: ${before}`;
      }
      if (after) {
        paramString += `, after: ${after}`;
      }
      if (on) {
        paramString += `, on: ${on}`;
      }
      consoleWriter.log(
        `Searching messages from ${channelName} with ${paramString} (limit:${messageLimit.toString()})`
      );
    }

    const channelMessages: Message[] = await client.searchMessagesByName(
      query,
      config.team,
      channelName,
      before,
      after,
      on,
      messageLimit
    );

    consoleWriter.log(`Found ${channelMessages.length.toString()} messages`);

    messages.push({
      type: 'text' as const,
      text: JSON.stringify({
        channel: channelName,
        messages: channelMessages,
      }),
    });
  }

  return {
    content: messages,
  };
};

export const mattermostSearch = {
  name,
  description,
  parameters,
  execute,
};
