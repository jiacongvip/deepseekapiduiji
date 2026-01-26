import fs from 'fs-extra';
import path from 'path';

import Response from '@/lib/response/Response.ts';
import chat from "./chat.ts";
import ping from "./ping.ts";
import token from './token.js';
import models from './models.ts';

async function readStaticHtml(filename: string) {
    const candidates = [
        path.join(path.resolve(), 'public', filename),
        path.join(path.resolve(), 'dist', filename),
        path.join(path.resolve(), filename),
    ];
    for (const filePath of candidates) {
        if (await fs.pathExists(filePath)) return fs.readFile(filePath);
    }
    throw new Error(`Static page not found: ${filename}`);
}

export default [
    {
        get: {
            '/': async () => {
                const content = await readStaticHtml('welcome.html');
                return new Response(content, {
                    type: 'html',
                    headers: {
                        Expires: '-1'
                    }
                });
            }
            ,
            '/chat': async () => {
                const content = await readStaticHtml('chat.html');
                return new Response(content, {
                    type: 'html',
                    headers: {
                        Expires: '-1'
                    }
                });
            }
            ,
            '/public/welcome.html': async () => {
                const content = await readStaticHtml('welcome.html');
                return new Response(content, {
                    type: 'html',
                    headers: {
                        Expires: '-1'
                    }
                });
            }
            ,
            '/public/chat.html': async () => {
                const content = await readStaticHtml('chat.html');
                return new Response(content, {
                    type: 'html',
                    headers: {
                        Expires: '-1'
                    }
                });
            }
            ,
            '/favicon.ico': async () => {
                return new Response('', {
                    statusCode: 204,
                    headers: {
                        Expires: '-1'
                    }
                });
            }
        }
    },
    chat,
    ping,
    token,
    models
];
