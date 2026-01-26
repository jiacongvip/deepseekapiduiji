import fs from 'fs-extra';

import Response from '@/lib/response/Response.ts';
import chat from "./chat.ts";
import images from "./images.ts";
import ping from "./ping.ts";
import token from './token.ts';
import models from './models.ts';
import claude from './claude.ts';
import gemini from './gemini.ts';

export default [
    {
        get: {
            '/': async () => {
                const content = await fs.readFile('public/welcome.html');
                return new Response(content, {
                    type: 'html',
                    headers: {
                        Expires: '-1'
                    }
                });
            }
        }
    },
    chat,
    claude,
    gemini,
    images,
    ping,
    token,
    models
];