import type { Plugin } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const dangerous = [
  /(^|\s)sudo(\s|$)/i,
  /(^|\s)(apt|apt-get|yum|dnf|pacman)(\s|$)/i,
  /rm\s+-rf\s+\/(\s|$)/i,
  /(^|\s)mkfs(\.|\s)/i,
  /(^|\s)dd\s+if=/i,
  /git\s+push\s+.*--force/i,
  /(curl|wget)[^|;&]*\|\s*(bash|sh)(\s|$)/i,
]

const secretKey = /(api[_-]?key|token|password|authorization|secret)/i
const projectRuntime = /(^|\s)(python|python3|pip|pip3|torchrun|accelerate|deepspeed)(\s|$)/i
const readOnlyWhileWaiting = /^\s*(pwd|ls|find|rg|grep|cat|head|tail|tree|git\s+(status|log|show|diff|rev-parse)|paper-repro(?:\s+--workspace\s+\S+)?\s+(status|doctor|paths|runs\s+list|decisions\b|env\s+show|models\s+show|mcp\s+status|paper\s+policy\s+show|code\s+show))\b/i

function enabled(root: string): boolean {
  return fs.existsSync(path.join(root, ".paper-repro", "enabled.json"))
}

function projectEnvironment(root: string): { name?: string; prefix?: string; enforce?: boolean } | null {
  try {
    const configPath = path.join(root, ".paper-repro", "config.json")
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"))
    const env = config.execution_env
    if (!env || !env.prefix) return null
    return { name: env.name, prefix: path.resolve(env.prefix), enforce: config.enforce_execution_env !== false }
  } catch {
    return null
  }
}

function sanitize(value: unknown, depth = 0): unknown {
  if (depth > 5) return "<TRUNCATED>"
  if (typeof value === "string") {
    const redacted = value.replace(/(api[_-]?key|token|password|authorization|secret)\s*[:=]\s*\S+/gi, "$1=<REDACTED>")
    return redacted.length > 4000 ? `${redacted.slice(0, 4000)}…<TRUNCATED>` : redacted
  }
  if (Array.isArray(value)) return value.slice(0, 100).map((item) => sanitize(item, depth + 1))
  if (value && typeof value === "object") {
    const output: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      output[key] = secretKey.test(key) ? "<REDACTED>" : sanitize(item, depth + 1)
    }
    return output
  }
  return value
}

function currentRun(root: string): string | null {
  const marker = path.join(root, ".paper-repro", "current")
  try {
    return fs.realpathSync(marker)
  } catch {
    const textMarker = path.join(root, ".paper-repro", "current.txt")
    try {
      const target = fs.readFileSync(textMarker, "utf8").trim()
      return fs.existsSync(target) ? target : null
    } catch {
      return null
    }
  }
}

function pendingBlockingDecisionCount(root: string): number {
  const run = currentRun(root)
  if (!run) return 0
  const decisionFile = path.join(run, "meta", "decisions.jsonl")
  try {
    const state = new Map<string, { pending: boolean; blocking: boolean }>()
    for (const line of fs.readFileSync(decisionFile, "utf8").split(/\r?\n/)) {
      if (!line.trim()) continue
      try {
        const record = JSON.parse(line)
        const id = String(record.decision_id || "")
        if (!id) continue
        if ((record.action || "opened") === "opened") {
          state.set(id, { pending: (record.status || "pending") === "pending", blocking: Boolean(record.blocking) })
        } else if (record.action === "resolved") {
          state.set(id, { pending: false, blocking: false })
        }
      } catch {
        // Ignore incomplete lines; the controller writes valid JSONL atomically per line.
      }
    }
    return [...state.values()].filter((item) => item.pending && item.blocking).length
  } catch {
    return 0
  }
}

function append(root: string, payload: unknown) {
  if (!enabled(root)) return
  const stateHome = path.join(root, ".paper-repro")
  const systemDir = path.join(stateHome, "system")
  fs.mkdirSync(systemDir, { recursive: true })
  const line = JSON.stringify({ ts: new Date().toISOString(), ...((sanitize(payload) ?? {}) as object) }) + "\n"
  fs.appendFileSync(path.join(systemDir, "opencode-events.jsonl"), line)
  const run = currentRun(root)
  if (run) {
    const meta = path.join(run, "meta")
    fs.mkdirSync(meta, { recursive: true })
    fs.appendFileSync(path.join(meta, "events.jsonl"), line)
  }
}

export const ReproAuditPlugin: Plugin = async ({ directory }) => {
  const root = path.resolve(directory)
  return {
    "shell.env": async (_input, output) => {
      output.env.REPRO_WORKSPACE = root
      output.env.PAPER_REPRO_CONTROL_CONDA = process.env.CONDA_PREFIX || ""
      const projectEnv = projectEnvironment(root)
      if (projectEnv?.prefix) {
        output.env.PAPER_REPRO_PROJECT_CONDA = projectEnv.prefix
        output.env.PAPER_REPRO_PROJECT_CONDA_NAME = projectEnv.name || path.basename(projectEnv.prefix)
      }
      if (!enabled(root)) return
      const cache = path.join(root, ".paper-repro", "cache")
      output.env.REPRO_STATE_HOME = path.join(root, ".paper-repro")
      output.env.HF_HOME = path.join(cache, "hf")
      output.env.HUGGINGFACE_HUB_CACHE = path.join(cache, "hf", "hub")
      output.env.TORCH_HOME = path.join(cache, "torch")
      output.env.XDG_CACHE_HOME = cache
      output.env.WANDB_MODE = output.env.WANDB_MODE || "offline"
      output.env.TOKENIZERS_PARALLELISM = output.env.TOKENIZERS_PARALLELISM || "false"
    },
    "tool.execute.before": async (input, output) => {
      if (!enabled(root)) return
      append(root, { type: "tool.before", tool: input.tool, args: output.args })
      if (input.tool === "bash") {
        const command = String(output.args.command ?? "")
        if (!process.env.CONDA_PREFIX || process.env.CONDA_DEFAULT_ENV === "base") {
          throw new Error("Blocked: OpenCode must run inside a dedicated active Conda environment")
        }
        if (dangerous.some((rule) => rule.test(command))) {
          throw new Error(`Blocked dangerous command: ${command}`)
        }
        const pendingDecisions = pendingBlockingDecisionCount(root)
        if (pendingDecisions > 0 && !readOnlyWhileWaiting.test(command)) {
          throw new Error(
            `WAITING_FOR_DECISION: ${pendingDecisions} pending decision(s) block mutating Bash commands. ` +
            "Use /repro-decisions checkpoint or paper-repro decisions checkpoint, then resolve the selected options."
          )
        }
        const projectEnv = projectEnvironment(root)
        const activePrefix = process.env.CONDA_PREFIX ? path.resolve(process.env.CONDA_PREFIX) : ""
        const usesController = /(^|\s)paper-repro(\s|$)/.test(command) || /(^|\s)conda\s+run(\s|$)/.test(command)
        if (projectRuntime.test(command) && !usesController) {
          if (!projectEnv) {
            throw new Error(
              "Blocked project runtime command: no project Conda is configured. " +
              "Use repro_environment/create or paper-repro env create/use first, then run through repro_exec."
            )
          }
          if (projectEnv.enforce && projectEnv.prefix && projectEnv.prefix !== activePrefix) {
            throw new Error(
              `Blocked project runtime command in control Conda ${process.env.CONDA_DEFAULT_ENV || activePrefix}. ` +
              `Configured project Conda is ${projectEnv.name || projectEnv.prefix}. Use repro_exec or conda run -p ${projectEnv.prefix}.`
            )
          }
        }
      }
      if (input.tool === "read") {
        const filePath = String(output.args.filePath ?? "")
        if (/(^|\/)\.env(\.|$)/.test(filePath) && !filePath.endsWith(".env.example")) {
          throw new Error("Blocked: secrets files must not be read")
        }
      }
      if (["edit", "write", "patch"].includes(input.tool)) {
        const pendingDecisions = pendingBlockingDecisionCount(root)
        const filePath = String(output.args.filePath ?? output.args.path ?? "")
        const resolved = filePath ? path.resolve(root, filePath) : ""
        const internal = resolved.startsWith(path.join(root, ".paper-repro") + path.sep)
        if (pendingDecisions > 0 && !internal) {
          throw new Error(
            `WAITING_FOR_DECISION: ${pendingDecisions} pending decision(s) block project file edits. ` +
            "Resolve the decision checkpoint before changing source or configuration files."
          )
        }
      }
    },
    "tool.execute.after": async (input, output) => {
      if (!enabled(root)) return
      append(root, { type: "tool.after", tool: input.tool, output })
    },
    event: async ({ event }) => {
      if (!enabled(root)) return
      append(root, { type: event.type, event })
    },
  }
}
