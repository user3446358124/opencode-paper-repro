import { tool } from "@opencode-ai/plugin"

function workspaceOf(context: any): string {
  return String(context.worktree || context.directory || process.cwd())
}

function present(value: any): boolean {
  if (value === undefined || value === null) return false
  const text = String(value).trim().toLowerCase()
  return text !== "" && text !== "undefined" && text !== "null" && text !== "none"
}

function pushOptional(args: string[], flag: string, value: any) {
  if (present(value)) args.push(flag, String(value))
}

async function runCLI(context: any, args: string[]) {
  const workspace = workspaceOf(context)
  const proc = Bun.spawn(["paper-repro", "--workspace", workspace, ...args], {
    cwd: workspace,
    env: { ...process.env, REPRO_WORKSPACE: workspace },
    stdout: "pipe",
    stderr: "pipe",
  })
  const [stdout, stderr, code] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])
  const output = `${stdout}${stderr}`.trim()
  if (code !== 0) throw new Error(output || `paper-repro exited with ${code}`)
  return output
}

export const start = tool({
  description: "Create a new auditable paper-reproduction run in the current OpenCode workspace",
  args: {
    repository: tool.schema.string().optional(),
    paper: tool.schema.string().optional(),
  },
  async execute(args, context) {
    return runCLI(context, ["init", "--repository", args.repository ?? "", "--paper", args.paper ?? ""])
  },
})

export const exec = tool({
  description: "Submit a project command to the persistent paper-repro scheduler and return immediately with a task_id. Long GPU/CPU jobs must use this instead of OpenCode bash.",
  args: {
    stage: tool.schema.string().describe("Stable stage name, e.g. eval-table-2"),
    command: tool.schema.string(),
    gpu_count: tool.schema.number().int().min(0).describe("Required: 0=CPU, 1=single GPU, N=multi-GPU job"),
    name: tool.schema.string().optional(),
    gpu_ids: tool.schema.array(tool.schema.number().int().min(0)).optional(),
    min_free_memory_mb: tool.schema.number().int().min(0).optional(),
    timeout_seconds: tool.schema.number().int().positive().optional(),
    estimate_seconds: tool.schema.number().int().nonnegative().optional(),
    priority: tool.schema.number().int().optional(),
    dependencies: tool.schema.array(tool.schema.string()).optional(),
    parallel_group: tool.schema.string().optional(),
    progress_adapter: tool.schema.object({
      type: tool.schema.enum(["auto", "native", "tqdm", "jsonl-line-count", "line-count", "file-count", "regex-log"]),
      path: tool.schema.string().optional(),
      total: tool.schema.number().optional(),
      unit: tool.schema.string().optional(),
      pattern: tool.schema.string().optional(),
      glob: tool.schema.string().optional(),
      message: tool.schema.string().optional(),
    }).optional(),
    output_paths: tool.schema.array(tool.schema.string()).optional(),
    secret_env: tool.schema.array(tool.schema.string()).optional().describe("Only variables explicitly authorized by paper-repro security policy may be injected"),
  },
  async execute(args, context) {
    const cliArgs = [
      "runtime", "submit",
      "--name", present(args.name) ? String(args.name) : args.stage,
      "--stage", args.stage,
      "--command", args.command,
      "--gpu-count", String(args.gpu_count),
    ]
    if (args.gpu_ids && args.gpu_ids.length) cliArgs.push("--gpu-ids", args.gpu_ids.join(","))
    if (args.min_free_memory_mb !== undefined) cliArgs.push("--min-free-memory-mb", String(args.min_free_memory_mb))
    if (args.timeout_seconds !== undefined) cliArgs.push("--timeout", String(args.timeout_seconds))
    if (args.estimate_seconds !== undefined) cliArgs.push("--estimate", String(args.estimate_seconds))
    if (args.priority !== undefined) cliArgs.push("--priority", String(args.priority))
    for (const dep of args.dependencies ?? []) cliArgs.push("--depends-on", dep)
    pushOptional(cliArgs, "--parallel-group", args.parallel_group)
    if (args.progress_adapter) cliArgs.push("--progress-adapter", JSON.stringify(args.progress_adapter))
    for (const output of args.output_paths ?? []) cliArgs.push("--output", output)
    for (const name of args.secret_env ?? []) cliArgs.push("--secret-env", name)
    return runCLI(context, cliArgs)
  },
})

export const cmd = tool({
  description: "Run a bounded project-environment command synchronously for setup/diagnostics only. Do not use for training, evaluation, large downloads or background jobs; those must use repro_exec/runtime scheduler.",
  args: {
    stage: tool.schema.string().default("setup"),
    command: tool.schema.string(),
    timeout_seconds: tool.schema.number().int().positive().max(1800).default(600),
    estimate_seconds: tool.schema.number().int().nonnegative().optional(),
    secret_env: tool.schema.array(tool.schema.string()).optional(),
  },
  async execute(args, context) {
    const cliArgs = [
      "exec", "--stage", args.stage, "--command", args.command,
      "--timeout", String(args.timeout_seconds),
    ]
    if (args.estimate_seconds !== undefined) cliArgs.push("--estimate", String(args.estimate_seconds))
    for (const name of args.secret_env ?? []) cliArgs.push("--secret-env", name)
    return runCLI(context, cliArgs)
  },
})

export const download = tool({
  description: "Download a large HTTP(S) asset with resume, byte progress, speed, ETA, SHA256 and artifact registration",
  args: {
    url: tool.schema.string(),
    output: tool.schema.string(),
    stage: tool.schema.string().default("assets"),
    kind: tool.schema.string().default("download"),
    sha256: tool.schema.string().optional(),
  },
  async execute(args, context) {
    const cliArgs = [
      "download", "--url", args.url, "--output", args.output,
      "--stage", args.stage, "--kind", args.kind,
    ]
    if (args.sha256) cliArgs.push("--sha256", args.sha256)
    return runCLI(context, cliArgs)
  },
})

export const security = tool({
  description: "Inspect paper-repro execution security. Project code is sandboxed and receives no persisted secrets by default.",
  args: {
    action: tool.schema.enum(["show"]),
  },
  async execute(_args, context) {
    return runCLI(context, ["security", "show"])
  },
})

export const status = tool({
  description: "Return the current run stage, progress, ETA, issue count and latest GPU status",
  args: {},
  async execute(_args, context) {
    return runCLI(context, ["status", "--json"])
  },
})

export const runtime = tool({
  description: "Manage the persistent execution runtime: inspect/confirm GPU pool, save and submit an execution plan, inspect task/GPU state, or cancel/retry tasks. Runtime jobs continue even if the OpenCode agent session is idle.",
  args: {
    action: tool.schema.enum(["gpu-prepare", "gpu-inspect", "gpu-configure", "status", "tasks", "task", "plan-save", "plan-show", "plan-submit", "scheduler-status", "scheduler-start", "cancel", "retry", "remote-capabilities", "remote-discover", "remote-snapshot", "remote-decisions"]),
    gpu_ids: tool.schema.array(tool.schema.number().int().min(0)).optional(),
    remember_workspace: tool.schema.boolean().optional(),
    max_parallel: tool.schema.number().int().positive().optional(),
    allow_external_busy: tool.schema.boolean().optional(),
    tasks: tool.schema.array(tool.schema.object({
      task_id: tool.schema.string().optional(),
      display_name: tool.schema.string(),
      stage: tool.schema.string().optional(),
      command: tool.schema.string(),
      gpu_count: tool.schema.number().int().min(0),
      gpu_ids: tool.schema.array(tool.schema.number().int().min(0)).optional(),
      min_free_memory_mb: tool.schema.number().int().min(0).optional(),
      timeout_seconds: tool.schema.number().int().positive().optional(),
      estimate_seconds: tool.schema.number().int().nonnegative().optional(),
      priority: tool.schema.number().int().optional(),
      dependencies: tool.schema.array(tool.schema.string()).optional(),
      parallel_group_id: tool.schema.string().optional(),
      progress_adapter: tool.schema.object({
        type: tool.schema.enum(["auto", "native", "tqdm", "jsonl-line-count", "line-count", "file-count", "regex-log"]),
        path: tool.schema.string().optional(),
        total: tool.schema.number().optional(),
        unit: tool.schema.string().optional(),
        pattern: tool.schema.string().optional(),
        glob: tool.schema.string().optional(),
        message: tool.schema.string().optional(),
      }).optional(),
      output_paths: tool.schema.array(tool.schema.string()).optional(),
    })).optional(),
    task_id: tool.schema.string().optional(),
    include_command: tool.schema.boolean().optional(),
  },
  async execute(args, context) {
    if (args.action === "gpu-prepare") return runCLI(context, ["gpu", "prepare", "--json"])
    if (args.action === "gpu-inspect") return runCLI(context, ["gpu", "inspect", "--json"])
    if (args.action === "gpu-configure") {
      if (!args.gpu_ids) throw new Error("gpu-configure requires gpu_ids; use [] for CPU-only")
      const cliArgs = ["gpu", "configure", "--ids", args.gpu_ids.length ? args.gpu_ids.join(",") : "none"]
      if (args.remember_workspace) cliArgs.push("--remember-workspace")
      if (args.max_parallel !== undefined) cliArgs.push("--max-parallel", String(args.max_parallel))
      if (args.allow_external_busy) cliArgs.push("--allow-external-busy")
      return runCLI(context, cliArgs)
    }
    if (args.action === "status") return runCLI(context, ["runtime", "status", "--json"])
    if (args.action === "tasks") return runCLI(context, ["runtime", "tasks", "--json"])
    if (args.action === "task") {
      if (!args.task_id) throw new Error("task requires task_id")
      return runCLI(context, ["runtime", "task", args.task_id, "--json"])
    }
    if (args.action === "plan-show") return runCLI(context, ["runtime", "plan", "show"])
    if (args.action === "plan-save" || args.action === "plan-submit") {
      if (!args.tasks || !args.tasks.length) throw new Error(`${args.action} requires tasks`)
      const plan = JSON.stringify({ schema_version: 1, source: "opencode-agent", tasks: args.tasks })
      const op = args.action === "plan-save" ? "save" : "submit"
      return runCLI(context, ["runtime", "plan", op, "--tasks-json", plan])
    }
    if (args.action === "scheduler-status") return runCLI(context, ["scheduler", "status"])
    if (args.action === "scheduler-start") return runCLI(context, ["scheduler", "start"])
    if (args.action === "cancel" || args.action === "retry") {
      if (!args.task_id) throw new Error(`${args.action} requires task_id`)
      return runCLI(context, ["runtime", args.action, args.task_id])
    }
    if (args.action === "remote-capabilities") return runCLI(context, ["remote", "capabilities", "--json"])
    if (args.action === "remote-discover") return runCLI(context, ["remote", "discover", "--active", "--json"])
    if (args.action === "remote-decisions") return runCLI(context, ["remote", "decisions", "--json"])
    if (args.action === "remote-snapshot") {
      const cliArgs = ["remote", "snapshot", "--json"]
      if (args.include_command) cliArgs.push("--include-command")
      return runCLI(context, cliArgs)
    }
    throw new Error(`Unsupported runtime action: ${args.action}`)
  },
})

export const stage = tool({
  description: "Update the structured state after an audit or orchestration stage",
  args: {
    stage: tool.schema.string(),
    status: tool.schema.string().default("running"),
    progress: tool.schema.number().min(0).max(1).optional(),
    message: tool.schema.string().default(""),
    eta_seconds: tool.schema.number().int().nonnegative().optional(),
    step: tool.schema.number().int().positive().optional(),
    step_total: tool.schema.number().int().positive().optional(),
    step_name: tool.schema.string().optional(),
    step_status: tool.schema.enum(["pending", "running", "completed", "failed", "blocked"]).optional(),
  },
  async execute(args, context) {
    const cliArgs = ["stage", "--stage", args.stage, "--status", args.status, "--message", args.message]
    if (args.progress !== undefined) cliArgs.push("--progress", String(args.progress))
    if (args.eta_seconds !== undefined) cliArgs.push("--eta", String(args.eta_seconds))
    if (args.step !== undefined) cliArgs.push("--step", String(args.step))
    if (args.step_total !== undefined) cliArgs.push("--step-total", String(args.step_total))
    if (args.step_name) cliArgs.push("--step-name", args.step_name)
    if (args.step_status) cliArgs.push("--step-status", args.step_status)
    return runCLI(context, cliArgs)
  },
})

export const environment = tool({
  description: "Show, select or create the Conda environment used for project commands; separate from the OpenCode control environment",
  args: {
    action: tool.schema.enum(["show", "use", "create"]),
    name: tool.schema.string().optional(),
    prefix: tool.schema.string().optional(),
    python: tool.schema.string().default("3.11"),
  },
  async execute(args, context) {
    if (args.action === "show") return runCLI(context, ["env", "show"])
    const selector = args.prefix ? ["--prefix", args.prefix] : ["--name", args.name ?? ""]
    if (args.action === "use") return runCLI(context, ["env", "use", ...selector])
    return runCLI(context, ["env", "create", ...selector, "--python", args.python])
  },
})

export const register = tool({
  description: "Register a downloaded or generated artifact with size and SHA256",
  args: {
    path: tool.schema.string(),
    kind: tool.schema.string(),
    source: tool.schema.string().optional(),
    revision: tool.schema.string().optional(),
  },
  async execute(args, context) {
    return runCLI(context, [
      "register", "--path", args.path, "--kind", args.kind,
      "--source", args.source ?? "", "--revision", args.revision ?? "",
    ])
  },
})

export const doctor = tool({
  description: "Diagnose the paper-reproduction installation, workspace, Conda, GPU and current-run state",
  args: {},
  async execute(_args, context) {
    return runCLI(context, ["doctor"])
  },
})

export const issue = tool({
  description: "Record a paper-repro/OpenCode system-function problem or optimization opportunity and enqueue an eligible guarded self-improvement candidate; do not use for project-specific dependency or experiment failures",
  args: {
    title: tool.schema.string(),
    details: tool.schema.string(),
    severity: tool.schema.enum(["info", "warning", "error", "critical"]).default("error"),
    component: tool.schema.string().default("opencode-agent"),
    category: tool.schema.string().default("system-function"),
    expected: tool.schema.string().default(""),
    optimization: tool.schema.string().default(""),
    stage: tool.schema.string().default(""),
    command: tool.schema.string().default(""),
    log: tool.schema.string().default(""),
  },
  async execute(args, context) {
    return runCLI(context, [
      "issue", "add", "--title", args.title, "--details", args.details,
      "--severity", args.severity, "--component", args.component,
      "--category", args.category, "--expected", args.expected, "--optimization", args.optimization,
      "--stage", args.stage, "--command", args.command, "--log", args.log,
    ])
  },
})

export const blocker = tool({
  description: "Record a project-specific reproduction blocker such as missing data, incompatible dependency, failing training command or unavailable checkpoint",
  args: {
    title: tool.schema.string(),
    details: tool.schema.string(),
    severity: tool.schema.enum(["info", "warning", "error", "critical"]).default("error"),
    component: tool.schema.string().default("project"),
    stage: tool.schema.string().default(""),
    command: tool.schema.string().default(""),
    log: tool.schema.string().default(""),
  },
  async execute(args, context) {
    return runCLI(context, [
      "blocker", "add", "--title", args.title, "--details", args.details,
      "--severity", args.severity, "--component", args.component,
      "--stage", args.stage, "--command", args.command, "--log", args.log,
    ])
  },
})

export const feedback = tool({
  description: "Create a sanitized diagnostic bundle for system feedback",
  args: {
    include_logs: tool.schema.boolean().default(false),
  },
  async execute(args, context) {
    return runCLI(context, args.include_logs ? ["feedback", "--include-logs"] : ["feedback"])
  },
})


export const vision = tool({
  description: "Use configured fallback vision models only when the active base model cannot natively inspect the requested images or PDF pages",
  args: {
    inputs: tool.schema.array(tool.schema.string()).min(1),
    prompt: tool.schema.string(),
    task: tool.schema.enum(["vision", "document", "ocr", "table", "chart", "formula"]).default("vision"),
    pages: tool.schema.string().default("1"),
    dpi: tool.schema.number().int().min(72).max(400).default(180),
    profile: tool.schema.string().optional(),
    output: tool.schema.string().optional(),
  },
  async execute(args, context) {
    const cliArgs = ["vision", "analyze", "--task", present(args.task) ? String(args.task) : "vision", "--prompt", args.prompt]
    if (present(args.pages)) cliArgs.push("--pages", String(args.pages))
    if (args.dpi !== undefined && args.dpi !== null) cliArgs.push("--dpi", String(args.dpi))
    for (const input of args.inputs) cliArgs.push("--input", input)
    pushOptional(cliArgs, "--profile", args.profile)
    pushOptional(cliArgs, "--output", args.output)
    return runCLI(context, cliArgs)
  },
})

export const models = tool({
  description: "Show effective native-first model routing and configured fallback multimodal profiles",
  args: {},
  async execute(_args, context) {
    return runCLI(context, ["models", "show"])
  },
})


export const paper = tool({
  description: "Inspect a PDF's text layer and visual structure or show the hybrid paper-audit policy",
  args: {
    action: tool.schema.enum(["inspect", "policy-show"]),
    input: tool.schema.string().optional(),
    vision_policy: tool.schema.enum(["targeted", "on-demand", "all-pages", "off"]).optional(),
  },
  async execute(args, context) {
    if (args.action === "policy-show") return runCLI(context, ["paper", "policy", "show"])
    const cliArgs = ["paper", "inspect", "--input", args.input ?? ""]
    if (args.vision_policy) cliArgs.push("--vision-policy", args.vision_policy)
    return runCLI(context, cliArgs)
  },
})

export const code = tool({
  description: "Build or show a static code index for repository-wide explanation, call-chain analysis and paper-to-code mapping",
  args: {
    action: tool.schema.enum(["index", "show"]),
  },
  async execute(args, context) {
    return runCLI(context, ["code", args.action])
  },
})

export const mcp = tool({
  description: "Show the installed native web and minimal MCP capability status for paper reproduction",
  args: {},
  async execute(_args, context) {
    return runCLI(context, ["mcp", "status"])
  },
})

export const decision = tool({
  description: "Assess, list, checkpoint or resolve adaptive human-in-the-loop decisions. Use before choices that materially affect results, cost, permissions, external side effects or irreversibility.",
  args: {
    action: tool.schema.enum(["policy-show", "policy-set", "assess", "list-pending", "checkpoint", "resolve"]),
    mode: tool.schema.enum(["autonomous", "balanced", "collaborative", "strict"]).optional(),
    scope: tool.schema.enum(["global", "workspace"]).default("workspace"),
    title: tool.schema.string().optional(),
    question: tool.schema.string().optional(),
    category: tool.schema.string().default("routine"),
    stage: tool.schema.string().default(""),
    impact: tool.schema.enum(["low", "medium", "high", "critical"]).default("medium"),
    reversibility: tool.schema.enum(["reversible", "partial", "irreversible"]).default("reversible"),
    confidence: tool.schema.number().min(0).max(1).default(0.9),
    changes_results: tool.schema.boolean().default(false),
    external_side_effect: tool.schema.boolean().default(false),
    estimated_hours: tool.schema.number().min(0).default(0),
    estimated_cost_cny: tool.schema.number().min(0).default(0),
    download_gb: tool.schema.number().min(0).default(0),
    patch_files: tool.schema.number().int().min(0).default(0),
    options: tool.schema.array(tool.schema.object({
      id: tool.schema.string(),
      label: tool.schema.string(),
      consequence: tool.schema.string().default(""),
      recommended: tool.schema.boolean().default(false),
    })).optional(),
    default_option: tool.schema.string().default(""),
    recommended_option: tool.schema.string().default(""),
    preference_key: tool.schema.string().default(""),
    context: tool.schema.string().default(""),
    decision_id: tool.schema.string().optional(),
    selected_option: tool.schema.string().optional(),
    remember: tool.schema.enum(["none", "workspace", "global"]).default("none"),
    note: tool.schema.string().default(""),
  },
  async execute(args, context) {
    if (args.action === "policy-show") return runCLI(context, ["decisions", "policy", "show"])
    if (args.action === "policy-set") {
      if (!args.mode) throw new Error("policy-set requires mode")
      return runCLI(context, ["decisions", "policy", "set", "--mode", args.mode, "--scope", args.scope])
    }
    if (args.action === "list-pending") return runCLI(context, ["decisions", "list", "--pending"])
    if (args.action === "checkpoint") {
      const cliArgs = ["decisions", "checkpoint"]
      if (args.stage) cliArgs.push("--stage", args.stage)
      return runCLI(context, cliArgs)
    }
    if (args.action === "resolve") {
      if (!args.decision_id || !args.selected_option) throw new Error("resolve requires decision_id and selected_option")
      return runCLI(context, [
        "decisions", "resolve", args.decision_id, "--option", args.selected_option,
        "--remember", args.remember, "--note", args.note,
      ])
    }
    if (!args.title || !args.question || !args.options || args.options.length < 2) {
      throw new Error("assess requires title, question and at least two options")
    }
    const cliArgs = [
      "decisions", "assess",
      "--title", args.title,
      "--question", args.question,
      "--category", args.category,
      "--stage", args.stage,
      "--impact", args.impact,
      "--reversibility", args.reversibility,
      "--confidence", String(args.confidence),
      "--estimated-hours", String(args.estimated_hours),
      "--estimated-cost-cny", String(args.estimated_cost_cny),
      "--download-gb", String(args.download_gb),
      "--patch-files", String(args.patch_files),
      "--options-json", JSON.stringify(args.options),
    ]
    pushOptional(cliArgs, "--default-option", args.default_option)
    pushOptional(cliArgs, "--recommended-option", args.recommended_option)
    pushOptional(cliArgs, "--preference-key", args.preference_key)
    pushOptional(cliArgs, "--context", args.context)
    if (args.changes_results) cliArgs.push("--changes-results")
    if (args.external_side_effect) cliArgs.push("--external-side-effect")
    return runCLI(context, cliArgs)
  },
})

export const self = tool({
  description: "Create and execute a guarded paper-repro self-improvement task in an isolated source snapshot. It only accepts system-level issues or explicit user improvement requests, never project-specific blockers.",
  args: {
    action: tool.schema.enum(["policy-show", "submit", "scan", "list", "prepare", "context", "tree", "search", "read", "write", "test", "diff", "propose", "auto", "status", "discard"]),
    improvement_id: tool.schema.string().optional(),
    issue_id: tool.schema.string().optional(),
    title: tool.schema.string().optional(),
    details: tool.schema.string().optional(),
    priority: tool.schema.enum(["low", "normal", "high", "critical"]).default("normal"),
    path: tool.schema.string().optional(),
    content: tool.schema.string().optional(),
    pattern: tool.schema.string().optional(),
    prefix: tool.schema.string().default(""),
    start: tool.schema.number().int().positive().default(1),
    end: tool.schema.number().int().nonnegative().default(0),
    limit: tool.schema.number().int().positive().max(500).default(200),
    summary: tool.schema.boolean().default(true),
    reason: tool.schema.string().default(""),
  },
  async execute(args, context) {
    const id = args.improvement_id ?? ""
    if (args.action === "policy-show") return runCLI(context, ["improve", "policy", "show"])
    if (args.action === "scan") return runCLI(context, ["improve", "scan"])
    if (args.action === "list") return runCLI(context, ["improve", "list"])
    if (args.action === "submit") {
      const cliArgs = ["improve", "submit", "--priority", args.priority]
      if (args.issue_id) cliArgs.push("--issue-id", args.issue_id)
      if (args.title) cliArgs.push("--title", args.title)
      if (args.details) cliArgs.push("--details", args.details)
      if (!args.issue_id) cliArgs.push("--source", "user-request")
      return runCLI(context, cliArgs)
    }
    if (!id) throw new Error(`${args.action} requires improvement_id`)
    if (args.action === "prepare") return runCLI(context, ["improve", "prepare", id])
    if (args.action === "context") return runCLI(context, ["improve", "context", id])
    if (args.action === "tree") return runCLI(context, ["improve", "tree", id, "--prefix", args.prefix, "--limit", String(args.limit)])
    if (args.action === "search") {
      if (!args.pattern) throw new Error("search requires pattern")
      return runCLI(context, ["improve", "search", id, "--pattern", args.pattern, "--ignore-case", "--limit", String(args.limit)])
    }
    if (args.action === "read") {
      if (!args.path) throw new Error("read requires path")
      return runCLI(context, ["improve", "read", id, "--path", args.path, "--start", String(args.start), "--end", String(args.end)])
    }
    if (args.action === "write") {
      if (!args.path || args.content === undefined) throw new Error("write requires path and content")
      const encoded = Buffer.from(args.content, "utf8").toString("base64")
      return runCLI(context, ["improve", "write", id, "--path", args.path, "--content-base64", encoded])
    }
    if (args.action === "test") return runCLI(context, ["improve", "test", id])
    if (args.action === "diff") {
      const cliArgs = ["improve", "diff", id]
      if (args.summary) cliArgs.push("--summary")
      return runCLI(context, cliArgs)
    }
    if (args.action === "propose") return runCLI(context, ["improve", "propose", id])
    if (args.action === "auto") return runCLI(context, ["improve", "auto", id])
    if (args.action === "status") return runCLI(context, ["improve", "status", id])
    if (args.action === "discard") return runCLI(context, ["improve", "discard", id, "--reason", args.reason])
    throw new Error(`Unsupported self-improvement action: ${args.action}`)
  },
})

export const publish = tool({
  description: "Prepare, privacy-scan, review and publish only the sanitized paper-repro system source to a user-owned GitHub repository. Never packages the current paper project, runtime state, PDFs, logs, datasets, checkpoints or credentials.",
  args: {
    action: tool.schema.enum(["policy-show", "configure", "auth-status", "list", "prepare", "scan", "review", "approve", "push", "abort", "purge-local"]),
    publication_id: tool.schema.string().optional(),
    improvement_id: tool.schema.string().optional(),
    owner: tool.schema.string().optional(),
    repository: tool.schema.string().optional(),
    visibility: tool.schema.enum(["public", "private", "internal"]).optional(),
    description: tool.schema.string().optional(),
    license: tool.schema.enum(["MIT", "none"]).optional(),
    copyright_holder: tool.schema.string().optional(),
    auth_method: tool.schema.enum(["gh", "token"]).optional(),
    token_env: tool.schema.string().optional(),
    existing_repo_mode: tool.schema.enum(["pull-request", "direct"]).optional(),
    sync_mode: tool.schema.enum(["managed-mirror", "preserve-extra"]).optional(),
    after_verified: tool.schema.enum(["off", "notify", "prepare"]).optional(),
    git_author_name: tool.schema.string().optional(),
    git_author_email: tool.schema.string().optional(),
    confirmation_phrase: tool.schema.string().optional(),
    acknowledge_warnings: tool.schema.boolean().default(false),
    reason: tool.schema.string().default(""),
    delete_session: tool.schema.boolean().default(false),
  },
  async execute(args, context) {
    if (args.action === "policy-show") return runCLI(context, ["publish", "policy", "show"])
    if (args.action === "auth-status") return runCLI(context, ["publish", "auth", "status"])
    if (args.action === "list") return runCLI(context, ["publish", "list"])
    if (args.action === "purge-local") return runCLI(context, ["publish", "purge-local", "--yes"])
    if (args.action === "configure") {
      const cliArgs = ["publish", "configure"]
      if (args.owner) cliArgs.push("--owner", args.owner)
      if (args.repository) cliArgs.push("--repository", args.repository)
      if (args.visibility) cliArgs.push("--visibility", args.visibility)
      if (args.description !== undefined) cliArgs.push("--description", args.description)
      if (args.license) cliArgs.push("--license", args.license)
      if (args.copyright_holder !== undefined) cliArgs.push("--copyright-holder", args.copyright_holder)
      if (args.auth_method) cliArgs.push("--auth-method", args.auth_method)
      if (args.token_env) cliArgs.push("--token-env", args.token_env)
      if (args.existing_repo_mode) cliArgs.push("--existing-repo-mode", args.existing_repo_mode)
      if (args.sync_mode) cliArgs.push("--sync-mode", args.sync_mode)
      if (args.after_verified) cliArgs.push("--after-verified", args.after_verified)
      if (args.git_author_name !== undefined) cliArgs.push("--git-author-name", args.git_author_name)
      if (args.git_author_email !== undefined) cliArgs.push("--git-author-email", args.git_author_email)
      return runCLI(context, cliArgs)
    }
    if (args.action === "prepare") {
      const cliArgs = ["publish", "prepare"]
      if (args.improvement_id) cliArgs.push("--improvement-id", args.improvement_id)
      return runCLI(context, cliArgs)
    }
    if (!args.publication_id) throw new Error(`${args.action} requires publication_id`)
    if (args.action === "scan") return runCLI(context, ["publish", "scan", args.publication_id])
    if (args.action === "review") return runCLI(context, ["publish", "review", args.publication_id])
    if (args.action === "approve") {
      if (!args.confirmation_phrase) throw new Error("approve requires the exact confirmation phrase shown to the user")
      const cliArgs = ["publish", "approve", args.publication_id, "--confirm", args.confirmation_phrase]
      if (args.acknowledge_warnings) cliArgs.push("--ack-warnings")
      return runCLI(context, cliArgs)
    }
    if (args.action === "push") return runCLI(context, ["publish", "push", args.publication_id])
    if (args.action === "abort") {
      const cliArgs = ["publish", "abort", args.publication_id, "--reason", args.reason]
      if (args.delete_session) cliArgs.push("--delete-session")
      return runCLI(context, cliArgs)
    }
    throw new Error(`Unsupported publish action: ${args.action}`)
  },
})
