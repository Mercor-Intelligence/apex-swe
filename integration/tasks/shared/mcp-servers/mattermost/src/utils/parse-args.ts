type ParsedArgs = Record<string, string | boolean>;

export function parseArgs(args: string[] = process.argv.slice(2)): ParsedArgs {
  const parsedArgs: ParsedArgs = {};

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    if (arg.startsWith('--')) {
      const key = arg.slice(2);

      if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
        parsedArgs[key] = args[i + 1];
        i++;
      } else {
        parsedArgs[key] = true;
      }
    }
  }

  return parsedArgs;
}
