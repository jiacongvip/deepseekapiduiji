import _ from "lodash";

import Request from "@/lib/request/Request.ts";
import Response from "@/lib/response/Response.ts";
import chat from "@/api/controllers/chat.ts";

export default {
  prefix: "/v1/chat",

  post: {
    "/completions": async (request: Request) => {
      request
        .validate('body.conversation_id', v => _.isUndefined(v) || _.isString(v))
        .validate("body.messages", _.isArray)
        .validate("headers.authorization", _.isString);
      // ticket切分
      const tokens = chat.tokenSplit(request.headers.authorization);
      // 随机挑选一个ticket
      const token = _.sample(tokens);
      const { model, conversation_id: convId, messages, search_type, stream, include_references } = request.body;
      if (stream) {
        const stream = await chat.createCompletionStream(
          model,
          messages,
          search_type,
          token,
          convId
        );
        return new Response(stream, {
          type: "text/event-stream",
        });
      } else
        {
          const result = await chat.createCompletion(
            model,
            messages,
            search_type,
            token,
            convId
          );
          if (include_references) {
            const content = _.get(result, "choices[0].message.content", "");
            const urls = _.isString(content)
              ? content.match(/https?:\/\/[-a-zA-Z0-9@:%._\+~#=]{2,256}\.[a-z]{2,6}\b([-a-zA-Z0-9@:%_\+.~#?&//=\,]*)/gi) || []
              : [];
            const normalized = _.uniq(
              urls.map(u => {
                try {
                  const url = new URL(u);
                  url.search = "";
                  return url.toString();
                } catch {
                  return u;
                }
              })
            );
            return { ...result, references: normalized };
          }
          return result;
        }
    },
  },
};
