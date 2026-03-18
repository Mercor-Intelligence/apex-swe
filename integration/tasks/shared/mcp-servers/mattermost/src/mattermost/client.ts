import axios from 'axios';
import type { AxiosInstance } from 'axios';
import cacheManager from '../utils/cache-manager.js';

interface Channel {
  id: string;
  create_at: number;
  update_at: number;
  team_id: string;
  type: string;
  display_name: string;
  name: string;
  header: string;
  purpose: string;
  last_post_at: number;
  total_msg_count: number;
  team_display_name: string;
  team_name: string;
  team_update_at: number;
}

interface Message {
  id: string;
  create_at: number;
  update_at: number;
  user_id: string;
  message: string;
  type: string;
  props?: {
    card?: string | null;
  };
  reply_count: number;
  last_reply_at: number;
}

interface Post {
  id: string;
  create_at: number;
  update_at: number;
  edit_at: number;
  delete_at: number;
  is_pinned: boolean;
  user_id: string;
  channel_id: string;
  root_id: string;
  original_id: string;
  message: string;
  type: string;
  props?: {
    card?: string;
    from_webhook?: string;
    override_icon_url?: string;
    override_username?: string;
    webhook_display_name?: string;
  };
  hashtags: string;
  file_ids: string[] | null;
  pending_post_id: string;
  reply_count: number;
  last_reply_at: number;
}

interface Team {
  id: string;
  create_at: number;
  update_at: number;
  delete_at: number;
  display_name: string;
  name: string;
  description?: string;
  email?: string;
  type: string;
  allowed_domains?: string;
  invite_id?: string;
  allow_open_invite?: boolean;
  policy_id?: string;
}

export class MattermostClient {
  private readonly client: AxiosInstance;
  private initialized = false;
  private teams: Team[] | null = null;
  private channels: Channel[] | null = null;

  constructor(
    private readonly endpoint: string,
    private readonly token: string
  ) {
    this.client = axios.create({
      baseURL: endpoint,
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  }

  async init(): Promise<void> {
    if (this.initialized) {
      return;
    }

    const teams = cacheManager.get('teams') as Team[] | null;
    if (teams) {
      this.teams = teams;
    } else {
      this.teams = await this._getTeams();
      cacheManager.set('teams', this.teams, 60 * 60);
    }

    const channels = cacheManager.get('channels') as Channel[] | null;
    if (channels) {
      this.channels = channels;
    } else {
      this.channels = await this._getChannels();
      cacheManager.set('channels', this.channels, 60 * 60);
    }

    this.initialized = true;
  }

  private async _getTeams(): Promise<Team[]> {
    const response = await this.client.get<Team[]>('/teams', {
      params: {
        page: 0,
        per_page: 200,
      },
    });

    return Object.values(response.data).map(team => ({
      id: team.id,
      create_at: team.create_at,
      update_at: team.update_at,
      delete_at: team.delete_at,
      display_name: team.display_name,
      name: team.name,
      description: team.description,
      email: team.email,
      type: team.type,
      allowed_domains: team.allowed_domains,
      invite_id: team.invite_id,
      allow_open_invite: team.allow_open_invite,
      policy_id: team.policy_id,
    }));
  }

  async getTeamInfo(teamName: string): Promise<Team | null> {
    if (!this.initialized) {
      await this.init();
    }

    const team = this.teams?.find(t => t.name === teamName || t.display_name === teamName);
    if (!team) {
      return null;
    }

    return team;
  }

  private async _getChannels(): Promise<Channel[]> {
    const response = await this.client.get<Channel[]>('/channels', {
      params: {
        page: 0,
        per_page: 200,
      },
    });

    return Object.values(response.data).map(channel => ({
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
    }));
  }

  async getChannels(restrictedChannelNames: string[] | undefined | null): Promise<Channel[]> {
    if (!this.initialized) {
      await this.init();
    }

    if (restrictedChannelNames && restrictedChannelNames.length > 0) {
      return this.channels?.filter(c => restrictedChannelNames.includes(c.name)) ?? [];
    }

    return this.channels ?? [];
  }

  async getChannelInfo(channelName: string): Promise<Channel | null> {
    if (!this.initialized) {
      await this.init();
    }

    const channel = this.channels?.find(
      c => c.name === channelName || c.display_name === channelName
    );
    if (!channel) {
      return null;
    }

    return channel;
  }

  async getChannelInfoById(channelId: string): Promise<Channel | null> {
    if (!this.initialized) {
      await this.init();
    }

    const channel = this.channels?.find(c => c.id === channelId);
    if (!channel) {
      return null;
    }

    return channel;
  }

  async getTargetChannelNames(
    channelNames: string[] | undefined | null,
    restrictedChannelNames: string[] | undefined | null
  ): Promise<string[]> {
    if (!this.initialized) {
      await this.init();
    }

    if (channelNames && channelNames.length > 0) {
      return channelNames;
    }

    if (restrictedChannelNames && restrictedChannelNames.length > 0) {
      return restrictedChannelNames;
    }

    if (this.channels && this.channels.length > 0) {
      return this.channels.map(c => c.name);
    }

    return [];
  }

  async getMessages(channelId: string, limit = 100): Promise<Message[]> {
    if (!this.initialized) {
      await this.init();
    }

    const response = await this.client.get<{ posts: Record<string, Post> }>(
      `/channels/${channelId}/posts`,
      {
        params: {
          page: 0,
          per_page: limit,
        },
      }
    );

    return Object.values(response.data.posts).map(post => ({
      id: post.id,
      create_at: post.create_at,
      update_at: post.update_at,
      user_id: post.user_id,
      message: post.message,
      type: post.type,
      props: {
        card: post.props?.card ?? null,
      },
      reply_count: post.reply_count,
      last_reply_at: post.last_reply_at,
    }));
  }

  async getMessagesByName(channelName: string, limit = 100): Promise<Message[]> {
    if (!this.initialized) {
      await this.init();
    }

    const channel = await this.getChannelInfo(channelName);
    if (!channel) {
      throw new Error(`Channel ${channelName} not found`);
    }

    return this.getMessages(channel.id, limit);
  }

  async searchMessages(
    query: string,
    teamId: string,
    channelName: string | null,
    before: string | undefined | null,
    after: string | undefined | null,
    on: string | undefined | null,
    limit = 100
  ): Promise<Message[]> {
    if (!this.initialized) {
      await this.init();
    }

    let terms = query;
    if (channelName) {
      terms += ` in:${channelName}`;
    }
    if (before) {
      terms += ` before:${before}`;
    }
    if (after) {
      terms += ` after:${after}`;
    }
    if (on) {
      terms += ` on:${on}`;
    }

    const response = await this.client.post<{ posts: Record<string, Post> }>(
      `/teams/${teamId}/posts/search`,
      {
        terms,
        is_or_search: false,
        page: 0,
        per_page: limit,
      }
    );

    return Object.values(response.data.posts).map(post => ({
      id: post.id,
      create_at: post.create_at,
      update_at: post.update_at,
      user_id: post.user_id,
      message: post.message,
      type: post.type,
      props: {
        card: post.props?.card ?? null,
      },
      reply_count: post.reply_count,
      last_reply_at: post.last_reply_at,
    }));
  }

  async searchMessagesByName(
    query: string,
    teamName: string,
    channelName: string | null,
    before: string | undefined | null,
    after: string | undefined | null,
    on: string | undefined | null,
    limit = 100
  ): Promise<Message[]> {
    if (!this.initialized) {
      await this.init();
    }

    const team = await this.getTeamInfo(teamName);
    if (!team) {
      throw new Error(`Team ${teamName} not found`);
    }

    return this.searchMessages(query, team.id, channelName, before, after, on, limit);
  }
}

export type { Channel, Message };
