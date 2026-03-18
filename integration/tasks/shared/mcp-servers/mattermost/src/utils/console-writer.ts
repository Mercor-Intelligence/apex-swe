import { config } from '../config/config.js';

export class ConsoleWriter {
  private readonly transport: string;

  constructor(transport: string) {
    this.transport = transport;
  }

  debug(message?: any, ...optionalParams: any[]): void {
    if (this.transport !== 'stdio') {
      console.debug(message, ...optionalParams); // eslint-disable-line @typescript-eslint/no-unsafe-argument
    }
  }

  log(message?: any, ...optionalParams: any[]): void {
    if (this.transport !== 'stdio') {
      console.log(message, ...optionalParams); // eslint-disable-line @typescript-eslint/no-unsafe-argument
    }
  }

  info(message?: any, ...optionalParams: any[]): void {
    if (this.transport !== 'stdio') {
      console.info(message, ...optionalParams); // eslint-disable-line @typescript-eslint/no-unsafe-argument
    }
  }

  warn(message?: any, ...optionalParams: any[]): void {
    if (this.transport !== 'stdio') {
      console.warn(message, ...optionalParams); // eslint-disable-line @typescript-eslint/no-unsafe-argument
    }
  }

  error(message?: any, ...optionalParams: any[]): void {
    if (this.transport !== 'stdio') {
      console.error(message, ...optionalParams); // eslint-disable-line @typescript-eslint/no-unsafe-argument
    }
  }
}

export const consoleWriter = new ConsoleWriter(config.transport);
