// Just enough of jsdom for the tests; avoids a second typings dependency.
declare module "jsdom" {
  export interface JSDOMOptions {
    url?: string;
    runScripts?: "outside-only" | "dangerously";
    pretendToBeVisual?: boolean;
    virtualConsole?: VirtualConsole;
  }
  export class VirtualConsole {
    on(event: string, listener: (...args: any[]) => void): this;
  }
  export class JSDOM {
    constructor(html?: string, options?: JSDOMOptions);
    readonly window: Window & typeof globalThis & { eval(code: string): unknown };
  }
}
