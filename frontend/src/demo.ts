// Guided demo: drives the real API through the 3-minute story so it can be recorded in one take.
// Nothing is faked; every step calls the same endpoints a person would click.

import { api, type IncidentDetail } from './api'

export interface DemoHooks {
  caption: (text: string, sub?: string) => void
  refresh: () => Promise<void>
  showPath: () => void
  openAsk: (question: string) => Promise<void>
  openMemory: (open: boolean) => void
  setIncident: (id: string | null) => void
  onWorld: () => Promise<void>
  signal: { aborted: boolean }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function waitFor(
  hooks: DemoHooks,
  check: () => Promise<IncidentDetail | null>,
  timeoutMs = 20000,
): Promise<IncidentDetail | null> {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    if (hooks.signal.aborted) return null
    const d = await check()
    if (d) return d
    await sleep(600)
  }
  return null
}

async function newestOpen(): Promise<IncidentDetail | null> {
  const list = await api.incidents()
  const open = list.find((i) => i.status !== 'resolved')
  return open ? api.incident(open.id) : null
}

export async function runDemo(h: DemoHooks): Promise<void> {
  const step = async (text: string, sub: string, ms: number) => {
    if (h.signal.aborted) throw new Error('stopped')
    h.caption(text, sub)
    await sleep(ms)
  }

  try {
    // The script narrates the NimbusPay story, so make sure that graph is live.
    await api.activateWorld('nimbuspay')
    await h.onWorld()
    await api.reset()
    h.setIncident(null)
    await h.refresh()
    await step('At 3 AM checkout is failing.', 'The alert is on checkout. The cause is not.', 3500)
    await step('One FalkorDB graph', 'services, dependencies, deploys, people, customers and every past incident', 3500)

    // 1. Inject the bad deploy with a decoy.
    h.caption('Injecting a bad deploy on auth-service…', 'plus an unrelated deploy on search-service, 4 minutes later')
    const out = await api.inject('bad-deploy', true)
    if (out.incident) h.setIncident(out.incident)
    await h.refresh()
    await step('Errors flow up synchronous dependency edges', 'checkout, web and payouts alert. auth-service never does.', 4000)

    // 2. Wait for the verdict.
    const inc = await waitFor(h, async () => {
      const d = await newestOpen()
      return d?.root_cause ? d : null
    })
    if (!inc) throw new Error('no verdict')
    await h.refresh()
    await step('Detective and Responder ran in parallel', 'they coordinated through Hypothesis nodes in the graph, not through prompts', 4000)
    const decoy = inc.hypotheses.find((x) => x.status === 'rejected')
    if (decoy) await step('The decoy is rejected', decoy.statement, 4000)
    await step(inc.summary, 'every bar in the breakdown is a graph signal', 4000)

    // 3. Evidence path.
    h.showPath()
    await step('The evidence path, hop by hop', (inc.evidence_path ?? []).join(' → '), 3500)
    const seen = inc.similar?.find((s) => s.id === inc.seen_before)
    if (seen) await step(`Seen before: ${seen.id}`, `${seen.title} — ${seen.actions.join('/')} fixed it in ${seen.ttm_min} min`, 4000)

    // 4. Approve the fix.
    const fix = inc.actions.find((a) => a.status === 'proposed' && a.kind !== 'page')
    if (fix) {
      h.caption('A human approves the rollback', fix.reason)
      await sleep(2500)
      await api.approve(fix.id)
      await h.refresh()
      await step('The map turns green', 'the Scribe writes a postmortem into the graph', 4000)
    }

    // 5. Memory.
    h.openMemory(true)
    await step('Memory', 'the rollback playbook gained a success; responders gained expertise', 4500)
    h.openMemory(false)

    // 6. Company brain.
    await step('The same graph is the company brain', 'ask why the system is built this way', 2000)
    await h.openAsk('Why does checkout call auth synchronously?')
    await step('Answers cite their sources', 'the ADR, who decided it, the Slack thread, highlighted on the map', 5000)

    await step('Firebreak', 'Stop incidents from spreading.', 4000)
  } catch (e) {
    if ((e as Error).message !== 'stopped') h.caption('Demo stopped', (e as Error).message)
  } finally {
    if (!h.signal.aborted) await sleep(1500)
    h.caption('', '')
  }
}
