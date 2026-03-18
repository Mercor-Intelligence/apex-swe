import { z, ZodTypeAny } from 'zod';
import { MattermostClient, Channel } from '../mattermost/client.js';
import { config } from '../config/config.js';

const name = 'mattermost_channels';

const description = 'Fetch channels from Mattermost. return json of channels information.';

const parameters = {
  limit: z
    .number()
    .min(1)
    .optional()
    .describe('Maximum number of channels to fetch. If not provided, uses the default limit.'),
};

type Args = z.objectOutputType<typeof parameters, ZodTypeAny>;

const execute = async ({ limit }: Args) => {
  const client = new MattermostClient(config.endpoint, config.token);

  const channels = await client.getChannels(config.channels);

  const resultChannels: Channel[] = [];
  for (const channel of channels) {
    if (limit && resultChannels.length >= limit) {
      break;
    }
    resultChannels.push(channel);
  }

  const result: { type: 'text'; text: string }[] = [];
  result.push({
    type: 'text' as const,
    text: JSON.stringify(
      Object.values(resultChannels).map(channel => ({
        id: channel.id,
        create_at: channel.create_at,
        update_at: channel.update_at,
        team_id: channel.team_id,
        type: channel.type,
        display_name: channel.display_name,
        name: channel.name,
        header: channel.header,
        purpose: channel.purpose,
        last_post_at: channel.last_post_at,
        total_msg_count: channel.total_msg_count,
        team_display_name: channel.team_display_name,
        team_name: channel.team_name,
        team_update_at: channel.team_update_at,
      }))
    ),
  });

  return {
    content: result,
  };
};

export const mattermostChannels = {
  name,
  description,
  parameters,
  execute,
};
