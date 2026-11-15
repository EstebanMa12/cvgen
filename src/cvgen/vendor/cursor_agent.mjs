/**
 * One-shot Cursor SDK runner used by cvgen.
 *
 * stdin: JSON { apiKey, model, cwd, prompt }
 * stdout: the agent's final text
 * stderr: progress
 *
 * Tools are read-only. The API key stays in this process.
 */
import { Agent, CursorAgentError } from "@cursor/sdk";
import { readFileSync } from "node:fs";

const input = JSON.parse(readFileSync(0, "utf8"));
for (const key of ["apiKey", "model", "cwd", "prompt"]) {
  if (!input[key]) {
    console.error(`Missing ${key}`);
    process.exit(1);
  }
}

let agent;
try {
  agent = await Agent.create({
    apiKey: input.apiKey,
    model: { id: input.model },
    local: { cwd: input.cwd, settingSources: [] },
    tools: ["read", "grep", "glob", "ls"],
  });
  const run = await agent.send(input.prompt);
  console.error(`agent=${agent.agentId} run=${run.id}`);
  const result = await run.wait();
  if (result.status !== "finished") {
    console.error(result.error?.message ?? `status=${result.status}`);
    process.exit(2);
  }
  process.stdout.write(result.result ?? "");
} catch (err) {
  if (err instanceof CursorAgentError) {
    console.error(err.message);
    process.exit(1);
  }
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
} finally {
  if (agent) await agent[Symbol.asyncDispose]();
}
