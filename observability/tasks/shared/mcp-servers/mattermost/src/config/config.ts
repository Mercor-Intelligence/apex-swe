import { z } from 'zod';
import { parseEnvs } from '../utils/parse-envs.js';
import { parseArgs } from '../utils/parse-args.js';

export const argsSchema = z.object({
  endpoint: z.string(),
  token: z.string(),
  team: z.string(),
  channels: z
    .string()
    .transform(val => (val ? val.split(',').filter(Boolean) : undefined))
    .optional(),
  limit: z.coerce.number().optional().default(100),
  transport: z.enum(['stdio', 'sse', 'http-stream']).optional().default('stdio'),
  port: z.coerce.number().optional().default(8201),
});

export type Config = z.infer<typeof argsSchema>;

const args = parseArgs();
const envs = parseEnvs();

export const config = argsSchema.parse({ ...envs, ...args });
