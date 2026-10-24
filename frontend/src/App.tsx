import { useEffect, useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  Check,
  Circle,
  Code2,
  Cpu,
  LoaderCircle,
  Play,
  Rocket,
  Workflow,
} from 'lucide-react';
import { supabase } from './supabase';

type AgentRole = 'architect' | 'coder' | 'deployer';

type AgentLog = {
  id: string;
  run_id: string;
  agent_role: AgentRole;
  payload: Record<string, unknown>;
  created_at: string;
};

const stages: {
  role: AgentRole;
  label: string;
  description: string;
  icon: typeof Cpu;
}[] = [
  {
    role: 'architect',
    label: 'Architect',
    description: 'Break down the task and define its requirements.',
    icon: Cpu,
  },
  {
    role: 'coder',
    label: 'Coder',
    description: 'Turn the plan into implementation artifacts.',
    icon: Code2,
  },
  {
    role: 'deployer',
    label: 'Deployer',
    description: 'Run the final deployment checks.',
    icon: Rocket,
  },
];

function isAgentLog(value: unknown): value is AgentLog {
  if (typeof value !== 'object' || value === null) return false;

  const row = value as Record<string, unknown>;
  return (
    typeof row.id === 'string' &&
    typeof row.run_id === 'string' &&
    (row.agent_role === 'architect' ||
      row.agent_role === 'coder' ||
      row.agent_role === 'deployer') &&
    typeof row.payload === 'object' &&
    row.payload !== null &&
    !Array.isArray(row.payload) &&
    typeof row.created_at === 'string'
  );
}

export default function App() {
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [prompt, setPrompt] = useState(
    'Build a rate-limited auth microservice',
  );
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const channel = supabase
      .channel('custom-all-channel')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'agent_logs' },
        (event) => {
          const newLog: unknown = event.new;
          if (!isAgentLog(newLog)) return;
          setLogs((current) => {
            if (current.some((log) => log.id === newLog.id)) return current;
            return [...current, newLog];
          });
        },
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED');
      });

    return () => {
      void supabase.removeChannel(channel);
    };
  }, []);

  const handleExecute = async () => {
    const task = prompt.trim();
    if (!task) {
      setError('Enter a task prompt before starting the pipeline.');
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setActiveRunId(null);
    setLogs([]);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: task }),
      });

      if (!response.ok) {
        throw new Error(`Pipeline request failed (${response.status}).`);
      }

      const result: unknown = await response.json();
      if (
        typeof result !== 'object' ||
        result === null ||
        !('run_id' in result) ||
        typeof result.run_id !== 'string'
      ) {
        throw new Error('The API response did not include a valid run ID.');
      }

      setActiveRunId(result.run_id);
    } catch (requestError) {
      console.error('Unable to start the agent pipeline:', requestError);
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to start the agent pipeline.',
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const runLogs = logs.filter((log) => log.run_id === activeRunId);

  return (
    <main className="min-h-screen bg-[#fbfbf9] px-4 py-6 text-[#3f3f3f] sm:px-8 sm:py-10">
      <div className="mx-auto max-w-7xl">
        <header className="mb-10">
          <div className="mb-8 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="rounded-xl border border-[#e2725b]/20 bg-[#e2725b]/10 p-2.5 text-[#e2725b]">
                <Workflow size={21} />
              </div>
              <div>
                <p className="text-sm font-semibold tracking-wide text-[#2b2b2b]">
                  HANDOFF<span className="text-[#e2725b]">OS</span>
                </p>
                <p className="text-xs text-gray-500">Multi-agent workspace</p>
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-500 shadow-sm">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  isConnected ? 'bg-[#e2725b]' : 'bg-amber-400'
                }`}
              />
              {isConnected ? 'Realtime connected' : 'Connecting to realtime'}
            </div>
          </div>

          <div className="mb-6">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-[#e2725b]">
              Agent orchestration
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#2b2b2b] sm:text-4xl">
              From prompt to deployment.
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">
              Follow each specialist as it works through your task in real time.
            </p>
          </div>

          <form
            className="flex flex-col gap-3 rounded-2xl border border-gray-200 bg-white p-3 shadow-sm sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              void handleExecute();
            }}
          >
            <label className="sr-only" htmlFor="task-prompt">
              Task prompt
            </label>
            <input
              id="task-prompt"
              type="text"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Describe the task for your agents..."
              className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-sm text-[#3f3f3f] outline-none placeholder:text-gray-400"
            />
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#e2725b] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[#d4634c] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? (
                <LoaderCircle className="animate-spin" size={16} />
              ) : (
                <Play size={15} fill="currentColor" />
              )}
              {isSubmitting ? 'Starting...' : 'Execute Task'}
            </button>
          </form>
          {error && (
            <p className="mt-3 text-sm text-red-500" role="alert">
              {error}
            </p>
          )}
          {activeRunId && (
            <p className="mt-3 font-mono text-xs text-gray-500">
              Run ID: <span className="text-[#3f3f3f]">{activeRunId}</span>
            </p>
          )}
        </header>

        <section
          aria-label="Agent pipeline stages"
          className="grid grid-cols-1 gap-4 md:grid-cols-3"
        >
          {stages.map((stage, index) => {
            const stageLogs = runLogs.filter(
              (log) => log.agent_role === stage.role,
            );
            const Icon = stage.icon;
            const isComplete = stageLogs.length > 0;
            const isCurrent =
              activeRunId !== null &&
              !isComplete &&
              runLogs.length === index;

            return (
              <article
                key={stage.role}
                className="flex min-h-[390px] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm"
              >
                <div className="border-b border-gray-100 p-5">
                  <div className="mb-5 flex items-center justify-between">
                    <span className="font-mono text-[11px] font-medium tracking-widest text-gray-400">
                      STAGE 0{index + 1}
                    </span>
                    <span
                      className={`flex h-7 w-7 items-center justify-center rounded-full border ${
                        isComplete
                          ? 'border-[#e2725b]/30 bg-[#e2725b]/10 text-[#e2725b]'
                          : isCurrent
                            ? 'border-sky-400/30 bg-sky-400/10 text-sky-500'
                            : 'border-gray-200 text-gray-400'
                      }`}
                    >
                      {isComplete ? (
                        <Check size={14} />
                      ) : isCurrent ? (
                        <Activity className="animate-pulse" size={14} />
                      ) : (
                        <Circle size={12} />
                      )}
                    </span>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="rounded-xl border border-gray-100 bg-gray-50 p-2.5 text-[#3f3f3f]">
                      <Icon size={18} />
                    </div>
                    <div>
                      <h2 className="font-medium text-[#2b2b2b]">{stage.label}</h2>
                      <p className="mt-1 text-xs leading-5 text-gray-500">
                        {stage.description}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="flex-1 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                      Agent output
                    </span>
                    {isComplete && (
                      <span className="text-[10px] font-medium uppercase tracking-wider text-[#e2725b]">
                        Complete
                      </span>
                    )}
                  </div>
                  <div className="h-[220px] overflow-auto rounded-xl border border-[#e2725b]/20 bg-[#f9e8e5] p-3">
                    {stageLogs.length ? (
                      stageLogs.map((log) => (
                        <pre
                          key={log.id}
                          className="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-[#3f3f3f]"
                        >
                          {JSON.stringify(log.payload, null, 2)}
                        </pre>
                      ))
                    ) : (
                      <div className="flex h-full items-center justify-center text-center">
                        <p className="text-xs text-gray-500">
                          {isCurrent
                            ? 'Agent is processing...'
                            : activeRunId
                              ? 'Waiting for previous stage...'
                              : 'Output will appear here'}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center justify-between border-t border-gray-100 px-5 py-3">
                  <span className="font-mono text-[10px] text-gray-400">
                    {stage.role.toUpperCase()}
                  </span>
                  <ArrowUpRight size={13} className="text-gray-400" />
                </div>
              </article>
            );
          })}
        </section>
      </div>
    </main>
  );
}