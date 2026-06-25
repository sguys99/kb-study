import { streamText, type CoreMessage } from "ai";
import { anthropic } from "@ai-sdk/anthropic";
import { openai } from "@ai-sdk/openai";

export const runtime = "nodejs";

function selectModel() {
  const provider = process.env.AI_PROVIDER ?? "anthropic";
  if (provider === "openai") {
    return openai(process.env.OPENAI_MODEL ?? "gpt-4o-mini");
  }
  return anthropic(process.env.ANTHROPIC_MODEL ?? "claude-sonnet-4-6");
}

export async function POST(req: Request) {
  const { messages }: { messages: CoreMessage[] } = await req.json();

  const result = streamText({
    model: selectModel(),
    messages,
    system: "You are a helpful assistant for a Next.js starter template.",
  });

  return result.toDataStreamResponse();
}
