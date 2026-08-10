import type { Plugin } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"
import os from "node:os"

const dangerous = [
  /(^|\s)sudo(\s|$)/i,
  /(^|\s)(apt|apt-get|yum|dnf|pacman)(\s|$)/i,
  /rm\s+-rf\s+\/(\s|$)/i,
  /(^|\s)mkfs(\.|\s)/i,
  /(^|\s)dd\s+if=/i,
  /git\s+push\s+.*--force/i,
  /(curl|wget)[^|;&]*\|\s*(bash|sh)(\s|$)/i,
]

const secretKey = /(api[_-]?key|access[_-]?key|token|password|passwd|authorization|secret|credential|private[_-]?key)/i
const secretEnvKey = /(^|_)(API_?KEY|ACCESS_?KEY|SECRET(?:_?KEY)?|TOKEN|PASSWORD|PASSWD|AUTHORIZATION|AUTH_?TOKEN|CREDENTIAL|PRIVATE_?KEY)(_|$)/i
const sensitiveShellPath = /(?:~\/|\$HOME\/|\/home\/[^/]+\/|\/root\/)(?:\.config\/paper-repro|\.ssh|\.aws|\.config\/gcloud|\.git-credentials|\.netrc|\.local\/share\/opencode\/auth\.json)|\/proc\/[^\s;&|]+\/environ/i
const sensitiveControlCommand = /paper-repro(?:\s+--workspace\s+\S+)?\s+secrets\s+(?:exec|edit)\b/i
const paperReproControlMode = Boolean(process.env.PAPER_REPRO_INSTALL_HOME || process.env.PAPER_REPRO_CONFIG_FILE || process.env.PAPER_REPRO_CONFIG_HOME)
const customSensitiveRoots = [process.env.PAPER_REPRO_CONFIG_HOME].filter((x): x is string => Boolean(x)).map((x) => path.resolve(x))
const customSensitiveFiles = [process.env.PAPER_REPRO_CONFIG_FILE, process.env.PAPER_REPRO_SECRETS_FILE, process.env.PAPER_REPRO_MCP_CONFIG]
  .filter((x): x is string => Boolean(x)).map((x) => path.resolve(x))
const sensitiveReadRoots = [
  path.join(os.homedir(), ".config", "paper-repro"),
  path.join(os.homedir(), ".ssh"),
  path.join(os.homedir(), ".aws"),
  path.join(os.homedir(), ".config", "gcloud"),
  path.join(os.homedir(), ".kube"),
  path.join(os.homedir(), ".docker"),
  path.join(os.homedir(), ".config", "gh"),
  path.join(os.homedir(), ".config", "huggingface"),
  ...customSensitiveRoots,
]
const sensitiveReadFiles = new Set([
  path.join(os.homedir(), ".git-credentials"),
  path.join(os.homedir(), ".netrc"),
  path.join(os.homedir(), ".npmrc"),
  path.join(os.homedir(), ".pypirc"),
  path.join(os.homedir(), ".condarc"),
  path.join(os.homedir(), ".local", "share", "opencode", "auth.json"),
  path.join(os.homedir(), ".cache", "huggingface", "token"),
  "/etc/shadow",
  "/etc/gshadow",
  "/etc/sudoers",
  ...customSensitiveFiles,
])
const liveSecretValues = Object.entries(process.env)
  .filter(([name, value]) => Boolean(value) && secretEnvKey.test(name) && String(value).length >= 8)
  .map(([, value]) => String(value))

function shellReferencesSensitive(command: string): boolean {
  if (sensitiveShellPath.test(command) || sensitiveControlCommand.test(command)) return true
  const home = os.homedir()
  const normalized = command.replaceAll("~/", `${home}/`).replace(/\$HOME\//g, `${home}/`)
  return [...sensitiveReadRoots, ...sensitiveReadFiles].some((item) => normalized.includes(item))
}
const projectRuntime = /(^|\s)(python|python3|pip|pip3|torchrun|accelerate|deepspeed)(\s|$)/i
const readOnlyWhileWaiting = /^\s*(pwd|ls|find|rg|grep|cat|head|tail|tree|git\s+(status|log|show|diff|rev-parse)|paper-repro(?:\s+--workspace\s+\S+)?\s+(status|doctor|paths|runs\s+list|decisions\b|env\s+show|models\s+show|mcp\s+status|paper\s+policy\s+show|code\s+show|runtime\s+(status|tasks|task|gpu|events)|remote\s+(snapshot|events|decisions)|gpu\s+(prepare|inspect|show)|scheduler\s+status))\b/i

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
    let redacted = value
      .replace(/(authorization\s*[:=]\s*bearer\s+)\S+/gi, "$1<REDACTED>")
      .replace(/((?:api[_-]?key|access[_-]?key|token|password|passwd|authorization|secret)\s*[:=]\s*)\S+/gi, "$1<REDACTED>")
      .replace(/((?:--api-key|--token|--password|--secret|--access-token)\s+)\S+/gi, "$1<REDACTED>")
      .replace(/\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b/g, "<REDACTED>")
    for (const secret of liveSecretValues) redacted = redacted.split(secret).join("<REDACTED>")
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

function appendRotating(filePath: string, line: string) {
  const configuredMb = Number(process.env.PAPER_REPRO_OPENCODE_EVENT_MAX_MB || "16")
  const maxBytes = Math.max(1, Number.isFinite(configuredMb) ? configuredMb : 16) * 1024 * 1024
  const backups = 3
  try {
    if (fs.existsSync(filePath) && fs.statSync(filePath).size + Buffer.byteLength(line) > maxBytes) {
      for (let i = backups; i >= 1; i--) {
        const src = i === 1 ? filePath : `${filePath}.${i - 1}`
        const dst = `${filePath}.${i}`
        if (!fs.existsSync(src)) continue
        if (fs.existsSync(dst)) fs.rmSync(dst, { force: true })
        fs.renameSync(src, dst)
      }
    }
  } catch {
    // Rotation failure must never block the reproduction workflow.
  }
  fs.appendFileSync(filePath, line)
}

function append(root: string, payload: unknown) {
  if (!enabled(root)) return
  const stateHome = path.join(root, ".paper-repro")
  const systemDir = path.join(stateHome, "system")
  fs.mkdirSync(systemDir, { recursive: true })
  const line = JSON.stringify({ ts: new Date().toISOString(), ...((sanitize(payload) ?? {}) as object) }) + "\n"
  appendRotating(path.join(systemDir, "opencode-events.jsonl"), line)
  const run = currentRun(root)
  if (run) {
    const meta = path.join(run, "meta")
    fs.mkdirSync(meta, { recursive: true })
    // Raw OpenCode events are debug telemetry only. Keep them separate from semantic run events.
    appendRotating(path.join(meta, "opencode-events.jsonl"), line)
  }
}

export const ReproAuditPlugin: Plugin = async ({ directory }) => {
  const root = path.resolve(directory)
  return {
    "shell.env": async (_input, output) => {
      if (!paperReproControlMode) return
      // OpenCode itself may need persisted secrets for providers/MCP, but arbitrary project shell commands must not inherit them.
      for (const name of Object.keys(process.env)) {
        if (secretEnvKey.test(name) || ["PAPER_REPRO_CONFIG_HOME", "PAPER_REPRO_CONFIG_FILE", "PAPER_REPRO_SECRETS_FILE", "PAPER_REPRO_MCP_CONFIG", "SSH_AUTH_SOCK", "GIT_ASKPASS"].includes(name)) {
          output.env[name] = ""
        }
      }
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
      if (!paperReproControlMode) return
      const projectEnabled = enabled(root)
      if (projectEnabled) append(root, { type: "tool.before", tool: input.tool, args: output.args })
      if (input.tool === "bash") {
        const command = String(output.args.command ?? "")
        if (shellReferencesSensitive(command)) {
          throw new Error("Blocked: shell command references a sensitive credential/configuration path, process environment, or secret-control command")
        }
        if (!projectEnabled) return
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
        if (projectRuntime.test(command)) {
          if (!projectEnv) {
            throw new Error(
              "Blocked project runtime command: no project Conda is configured. " +
              "Use repro_environment/create or paper-repro env create/use first."
            )
          }
          throw new Error(
            "Blocked long/project runtime command through OpenCode bash. " +
            "Python/pip/torchrun/accelerate/deepspeed tasks must be submitted with repro_exec or repro_runtime plan-submit. " +
            "The persistent scheduler owns the process so the agent loop cannot be held for hours."
          )
        }
      }
      if (input.tool === "read") {
        const filePath = String(output.args.filePath ?? "")
        const expanded = filePath.startsWith("~/") ? path.join(os.homedir(), filePath.slice(2)) : filePath
        const resolved = path.resolve(root, expanded)
        const sensitive = sensitiveReadFiles.has(resolved) || sensitiveReadRoots.some((prefix) => resolved === prefix || resolved.startsWith(prefix + path.sep))
        if (sensitive || (/(^|\/)\.env(\.|$)/.test(filePath) && !filePath.endsWith(".env.example"))) {
          throw new Error("Blocked: sensitive credential/configuration paths must not be read by the project agent")
        }
      }
      if (!projectEnabled) return
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
